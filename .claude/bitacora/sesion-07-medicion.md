<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

# Sesión 7 · 2026-08-07 (tarde) — blindar la medición mientras entrena `lora_v2`

Sesión de espera: `lora_v2` arrancó a la tarde y son 12-13 horas. La consigna fue mejorar el
sistema sin competir por la GPU, así que **nada de inferencia**: todo lo de acá es lógica,
tests y lectura de lo que ya estaba guardado.

**Resultado en un renglón:** los tests pasaron de **115 a 157**, se encontró y cerró **un bug
real** que iba a aparecer justo al medir `lora_v2`, se cerraron **dos pérdidas silenciosas de
datos**, y los números de F7 quedaron **auditados con un recuento independiente**.

---

## 1. Por qué se eligió la medición y no otra cosa

Los candidatos eran cuatro: blindar el medidor, cazar campos inventados, testear `acciones.ts`
y tapar los agujeros de `motor.ts`. Se eligió el medidor por una razón de oportunidad: en 13
horas termina `lora_v2` y **lo primero que se hace al terminar es medir**. Si el medidor está
mal, esas 13 horas no producen un número que signifique algo.

`motor.ts` se descartó a propósito: la re-especificación manda reescribirlo entero con la
cascada de la empresa, así que arreglar el viejo tiene alta chance de ser trabajo tirado.

---

## 2. El medidor: `normalizarCampo` no tenía un solo test

`importar-comprobantes.ts` son 251 líneas sin archivo de test, y ahí vive `normalizarCampo`,
la función que decide **qué cuenta como acierto**. De ella salen los 65/43/71/41% de F7 y de
ella iba a salir el número de `lora_v2`. Ya había mordido una vez (ver el bug de los "campos
corregidos" falsos en `reespecificacion.md`).

Se escribieron **17 tests de caracterización** sobre lógica pura. Aviso metodológico que vale
para el futuro: **un test de caracterización en verde no prueba nada nuevo** — clava el
contrato de código que ya existe. El valor está en los rojos.

Los 17 dieron **verde**. El contrato se sostiene:

```
monto   "$ 81.687,80"  ≡  columna "81687.80"       el bug viejo no volvió
monto   "250000"       ≡  columna "250000.00"      NUMERIC siempre da 2 decimales
monto   "$ 1.500"      →  ''                        ambiguo, no se adivina
monto   CBU de 22 díg. →  ''                        nunca truncado
coelsa  "N/A"          ≡  columna NULL              ausencia real, el modelo acertó
fecha   "27/06/2026"   ≡  columna "2026-06-27"
hora    "19:16 hs"     ≡  columna "19:16:00"
texto   "  GOMEZ  "    →  "GOMEZ"                   trim, y nada más
```

Uno de los 17 fija a propósito algo que **no** se hace: `"Mercado Pago"` y `"MERCADO PAGO"`
NO son iguales. Está medido que no cambia ningún acierto. Si algún día se decide plegar
mayúsculas, ese test obliga a que sea una decisión y no un efecto lateral.

---

## 3. 🐛 EL BUG: una fecha imposible tumbaba la corrida entera

Escribiendo los tests del importador contra `conciliador_test`, dos salieron **rojos**:

```
✖ una fecha imposible no puede hacer perder la corrida entera
  error: date/time field value out of range: "2026-02-30"   (Postgres 22008)
✖ una hora imposible tampoco puede hacer perder la corrida
  error: date/time field value out of range: "99:99"
```

**Causa raíz.** `aFecha` y `aHora` validaban la **forma** del valor, no que existiera:

```ts
// antes
const dmy = v.match(/^(\d{2})[/-](\d{2})[/-](\d{4})$/)
return dmy ? `${dmy[3]}-${dmy[2]}-${dmy[1]}` : null      // 30/02/2026 pasa
v.match(/^(\d{1,2}):(\d{2})/)                            // 99:99 pasa
```

**Consecuencia.** El importador corre en **una sola transacción**. Un comprobante con una
fecha alucinada hace `ROLLBACK` y se pierden **los otros 51**. No entra ninguno.

**No estaba cobrado.** Se midieron las 6 salidas guardadas: **0 fechas imposibles** en 312
registros (`salida_cruda`, `v2`, `v2_rescatado`, `v3`, `v4`, `validado`). Era latente. Y era
cuestión de tiempo: un modelo recién fine-tuneado escribe fechas que el zero-shot copiaba.

**El arreglo**, que es el contrato que el archivo ya declaraba en su propio comentario —
*"lo que no se puede convertir SIN ADIVINAR queda en NULL"*:

```ts
// el ida y vuelta por Date delata al 30 de febrero: se normaliza a marzo
const d = new Date(`${iso}T00:00:00Z`)
return Number.isNaN(d.getTime()) || !d.toISOString().startsWith(iso) ? null : iso
// y el rango real en el regex de la hora
v.match(/^([01]?\d|2[0-3]):([0-5]\d)/)
```

Sin dependencias nuevas. El valor crudo no se pierde: sigue en `extraccion.campos` y
`/revisar` lo muestra al lado del campo vacío.

**Verificado que no mueve ningún número existente:** aplicando la lógica vieja y la nueva
sobre los 312 registros reales, **0 fechas y 0 horas cambian de resultado**.

---

## 4. Los números de F7 quedaron auditados

Se recontaron los aciertos con **query y agregación propias**, distintas de las de la página:

```
corrida   comprobantes  aciertos/campos     %
v1              51        532/816          65%
v2              51        349/816          43%
v3              51        578/816          71%
v4              51        338/816          41%
sintetico        4         55/64           86%
```

**Coinciden exactamente.** Los 532/349/578/338 son ciertos. La advertencia sobre v3 sigue en
pie por el motivo conocido (es `corrida_base`, se corrigió partiendo de ella), no por un error
de cuenta.

**Dos cosas latentes que salieron del mismo recuento** — anotadas, NO tocadas:

1. `corridas/page.tsx:85` calcula `totalRevisados` contando **blobs de JSON distintos**, no
   comprobantes. Hoy da 55 por los dos caminos, así que no miente; miente el día que haya dos
   comprobantes revisados con los 16 campos idénticos.
2. Ese titular de 55 mezcla **51 reales + 4 sintéticos** cuyas etiquetas la bitácora da por
   rotas. Los denominadores por corrida están bien (51 en v1–v4), así que los porcentajes del
   informe están sanos.

---

## 5. `acciones.ts` dejó de ser interestable

**Por qué no tenía tests.** No era descuido: `acciones.ts` importa `next/cache`, que **no
resuelve fuera del bundler de Next**. Probado:

```
Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../next/cache'
```

Nada que lo importe se puede correr con `node --test`. Y es el archivo que escribe la verdad
de referencia — el que menos se puede permitir un error silencioso.

**La solución fue seguir el patrón que el repo ya tenía.** `acciones.ts` delega en
`importarExtracto`, `reconciliar` y `resolverAmbiguo`, todas en `lib/` y todas testeadas.
`guardarRevision` era la única con el SQL adentro de la Server Action. Se creó
**`web/src/lib/revision.ts`** = *lo que una persona escribe sobre un comprobante*, con las dos
formas que existen: corregir lo que extrajo el modelo, y cargar uno entero a mano.

### Las dos pérdidas silenciosas que se cerraron

Las dos escribían el **texto crudo del formulario** directo a columnas `NUMERIC`/`DATE`/`TIME`.
Tipear `$ 1.500,00` en monto tiraba un 500 y **se perdía la corrección entera**.

Ahora las dos aplican **todo o nada**: si un campo no se puede convertir sin adivinar, no se
escribe **ninguno** de los 16 y se avisa cuál fue.

> El criterio, que conviene no perder: un campo que llenó la IA se puede vaciar en silencio
> —el crudo sobrevive en `extraccion.campos` y la pantalla lo muestra—, pero **de lo que
> escribió una persona no queda ninguna otra copia**.

El test que más importa es `si hay un campo inválido no se escribe NADA: ni los que sí valían`.
Guardar 15 y perder uno callado es peor que fallar: la persona se va creyendo que revisó el
comprobante entero.

### `/revisar/[id]` se partió en dos

Para que lo tipeado **quede en pantalla** al rebotar, la acción no puede redirigir: tiene que
devolver estado, y eso pide `useActionState`, que solo corre en cliente.

```
revisar/[id]/page.tsx        servidor: la query, la imagen, arma los props
revisar/[id]/formulario.tsx  'use client': useActionState, el cartel rojo
```

⚠️ **El formulario NO puede importar nada de `lib/`**: esos módulos arrastran `pg` y no viajan
al navegador. Todo llega calculado por props. El único import es `import type { Campo }`, que
se borra al compilar.

### Y una corrección propia sobre la marcha

En `guardarComprobante` se puso primero el `INSERT` y después la escritura de la imagen. Eso
podía dejar **una fila sin su imagen** si fallaba el disco: un comprobante que no se puede
corregir nunca más. Se dio vuelta — se escribe la imagen, y si la fila se rechaza se borra el
archivo. **La imagen sobrevive solo si la fila existe.**

---

## 6. Verificado

```
$ pnpm test                157 · 157 pass · 0 fail        (la sesión arrancó en 115)
$ pnpm exec tsc --noEmit    limpio
$ pnpm lint                 sin quejas
$ curl las 9 pantallas      todas 200, incluidas /comprobante y /revisar/83
$ /revisar/83               16 inputs de campo + el id oculto, exacto
```

## ⚠️ Lo que NO se verificó, y por qué

**El ida y vuelta en el navegador de los dos carteles de error.** Que al mandar un monto
ambiguo aparezca el cartel rojo y los valores sigan en pantalla está probado a nivel lógica
(16 tests), pero el paso por `useActionState` no.

Para verlo habría que abrir `/revisar/83` con la extensión de Chrome, y esa pantalla tiene un
comprobante real: eso lo manda a un modelo en la nube y **rompe la regla 2**. No se hizo.

Queda como comprobación manual de 20 segundos:

```
http://localhost:3000/revisar/83  →  Monto: $ 1.500  →  Guardar
   debe aparecer el cartel rojo, el input en rojo, y "$ 1.500" TODAVÍA escrito
```

---

## 7. Correcciones a lo que decía la bitácora

| Decía | Es |
|---|---|
| `ia/extraer.py` … **FALTA `--adaptador`** | Está implementado, `extraer.py:174`, con chequeo de que el directorio exista |
| 52 comprobantes reales | **51.** Hay 51 `.jpeg` en `ia/comprobantes/` y 51 en la base |
| 72 comprobantes en la base | **71** = 51 reales + 20 sintéticos |

---

## 8. El dato incómodo que salió al mirar la base

```
conciliaciones:  no_verificable 63  ·  sospechoso 8  ·  verificado 0
CBU propios aprobados: 0
```

**El motor no verifica ni un solo comprobante.** No es un bug: cruza por `cuenta.cbu`, las tres
cuentas lo tienen en NULL, y nadie aprobó ningún CBU en `/cbu`. Con la regla actual eso es lo
correcto — sin lista de referencia no hay con qué comparar.

Pero significa que **hoy todo el valor demostrable del proyecto está del lado de la IA**.
Coincide con la prioridad que fijó el usuario, así que no es un problema de rumbo; es que la
mitad conciliadora está esperando dos datos que solo él puede dar.

---

## 9. La curva de `lora_v2` al cierre de la sesión

```
paso  1 ······ 15,35        paso 21 ······ 11,67
paso  6 ······ 63,18  ← el rebote normal de batch 1
paso 11 ······ 14,15        paso 26 ······ 10,96
paso 16 ······ 12,88        paso 32 ······  9,87
```

Desde el paso 8 baja **sin un solo rebote**. A la misma altura, `lora_v1` todavía saltaba
(12,97 en el paso 21 después de 12,82 en el 20). La firma del colapso de v1 no aparece.

**No es prueba de que funcione.** Eso se sabe midiendo sobre los 16 apartados que nunca se
entrenaron, y recién cuando termine.

---

## 10. Archivos que tocó esta sesión

```
➕ web/src/lib/importar-comprobantes.test.ts   26 tests. No existía
➕ web/src/lib/revision.ts                     la lógica que acciones.ts no podía testear
➕ web/src/lib/revision.test.ts                16 tests
➕ web/src/app/revisar/[id]/formulario.tsx     'use client' + useActionState
✏️ web/src/lib/importar-comprobantes.ts        aFecha y aHora arreglados; paraColumna expuesta
✏️ web/src/app/acciones.ts                     las dos escrituras pasaron a envoltorios
✏️ web/src/app/revisar/[id]/page.tsx           delega el form
```

**`paraColumna` es ahora el único camino** por el que un campo crudo se convierte:
`normalizarCampo`, `paraColumnas`, `guardarRevision` y `cargarComprobante` pasan todos por
ella. Antes había cuatro conversiones parecidas y ese es exactamente el patrón que produjo el
bug de los "campos corregidos" falsos.
