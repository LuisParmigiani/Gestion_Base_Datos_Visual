<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-07 · Sesión 5 — de qué fila del Excel salió cada movimiento

**Estado al empezar:** `lora_v1` entrenando (paso 21/300), Postgres arriba, 112 tests en verde,
2822 movimientos, 72 comprobantes. El usuario reportó que **las filas que muestra `/encontrar`
no son correctas**.

### El diagnóstico — tenía razón, y el error era grande

**El Excel estaba bien importado.** Los 2822 movimientos son correctos y siempre lo fueron.
Lo que estaba mal era **el número de fila**, que nunca se guardó: `/encontrar` lo *estimaba*
contando movimientos de la cuenta (`(SELECT count(*) … WHERE m2.id <= m.id) + 1`).

Esa cuenta se corre un lugar por cada fila que el Excel trae y la base no: las 21 repetidas
que descarta la `huella` UNIQUE, y las que no tienen fecha. El error se **acumula** hacia
abajo del archivo. Medido sobre los 2822:

```
SUCESION:  1196 de 1298 filas con el nº MAL (92,1%)  ·  desvío hasta 11
QUIQUE:    1195 de 1307 filas con el nº MAL (91,4%)  ·  desvío hasta  8
MARIELA:    140 de  217 filas con el nº MAL (64,5%)  ·  desvío hasta  2
```

En los 15 comprobantes que la pantalla efectivamente señalaba, el desvío iba de **4 a 9 filas**.
Nadie iba a encontrar nada mirando ahí.

### La decisión: backfill, no reimportar

El usuario propuso borrar y reimportar. Se recomendó lo contrario y lo aceptó:
`movimiento` está referenciada por `conciliacion` y hay 72 comprobantes cargados, así que
borrar arrastra. La `huella` UNIQUE ya identifica cada fila unívocamente, así que alcanza con
**agregar las columnas y completarlas releyendo el Excel**. Cero borrado, y queda idempotente.

### Lo que se construyó

| Archivo | Qué cambia |
|---|---|
| `web/migraciones/005_origen_excel.sql` | `hoja TEXT` + `fila INTEGER` en `movimiento`. Idempotente |
| `web/src/lib/importar.ts` | `eachRow` ya recibía el nº de fila real y se tiraba. Ahora un `Map` huella→fila y un `UPDATE … FROM UNNEST` después del INSERT |
| `web/src/app/encontrar/page.tsx` | Usa `m.hoja, m.fila`. Se sacó el `~` de "fila ~191": ya no es aproximada |
| `web/src/lib/importar.test.ts` | 3 tests nuevos |

**El origen se escribe en un `UPDATE` aparte y no en el `INSERT`.** Es lo que permite que
completar los 2822 que ya estaban sea el mismo código que usar el importador de siempre:
`pnpm importar` inserta 0 y rellena todo. Un script de backfill aparte habría sido un segundo
camino que se desincroniza.

`filaDe` se queda con la **primera** aparición de cada huella, igual que el `ON CONFLICT DO
NOTHING`: si el Excel repite una fila, la que existe en la base es la primera.

### TDD, con el rojo mirado

Los 3 tests se escribieron antes. Fallaron con `column "hoja" of relation "movimiento" does
not exist` — rojo por el motivo correcto. El que más importa:

```
`888` está en la fila 11 del .xlsx de prueba: antes vienen la repetida (9, que no entra
por la huella) y la que solo trae SALDO (10, que se saltea). Es el 8º movimiento de
SUCESION en la base, así que la cuenta vieja daba 9. Dos filas de desvío, en 11 filas.
```

El tercero apaga `hoja`/`fila` a NULL a propósito y reimporta, que es exactamente el camino
que se corrió sobre la base real.

### Verificado

```
$ pnpm test
tests 115 · pass 115 · fail 0        (112 de antes + 3 nuevos)

$ psql -f migraciones/005_origen_excel.sql -d conciliador
BEGIN / ALTER TABLE / COMMENT / COMMIT

$ pnpm importar ../TRANSFERENCIAS.xlsx
leídas 2843 · nuevas 0 · duplicadas 2843     ← no insertó nada, como debía

$ psql -d conciliador
total 2822 · sin_fila 0 · sin_hoja 0
MARIELA  217 filas, de la 2 a la 220, 217 distintas
QUIQUE  1307 filas, de la 2 a la 1316, 1307 distintas
SUCESION 1298 filas, de la 2 a la 1310, 1298 distintas

$ tsc --noEmit   sin errores      $ pnpm lint   sin quejas
$ curl /encontrar                 HTTP 200, muestra "SUCESION · fila 191"
```

**La verificación que cierra el asunto:** un script comparó, para los **2822**, que la celda
del Excel en esa `(hoja, fila)` tenga la misma fecha, el mismo importe crudo, el mismo
`NRO TRANSACCION` y la misma descripción que la base.

```
movimientos comparados: 2822
  los 4 campos coinciden con esa fila del Excel: 2822
  descripcion distinta: 0 · importe: 0 · fecha: 0 · nro: 0
```

El script vive en el directorio temporal del job, no en el repo: es un chequeo de una sola vez.
Solo imprime cuentas, nunca valores — la regla 2 sigue en pie.

> ⚠️ **`pnpm db:migrar` no se corrió**, porque las migraciones 001 y 002 no son idempotentes
> (`ADD COLUMN` pelado) y el script las corre todas. Se aplicó **solo la 005** con `psql`.
> Vale para cualquier migración futura sobre la base real.

### Lo que NO cambió, y hay que tenerlo claro

Arreglar la fila **no hace que los comprobantes crucen**. `/encontrar` sigue mostrando:

```
0 por nro de transacción + CUIT · 90%
19 por monto + fecha · 50%       ← coincidencias casuales: ninguna sobrevive al CUIT
53 sin encontrar
```

Es lo esperado y ya estaba medido: el Excel y los 52 comprobantes son dos ejemplos sin
relación. Lo que cambió es que, cuando el usuario vaya a buscar a mano, **la fila que le
decimos es la verdadera**.

### La bitácora, partida

Llegó a 1571 líneas y se leía entera al empezar cada sesión. Se partió en dos niveles —
`BITACORA.md` con el estado y el índice, `.claude/bitacora/*.md` con el relato de cada sesión —
y se actualizó la regla de `CLAUDE.md` que decía que los documentos eran cuatro y no se creaban
más. Nada se borró: los cinco archivos son los cortes exactos del original.

Al partirlo apareció que **la sesión 2 había perdido su encabezado** en algún momento: su
relato arrancaba directo con "Estado al empezar". Se le devolvió.
