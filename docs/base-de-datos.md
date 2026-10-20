# La base de datos

> Para saber más. Acá está el detalle de cada tabla, de los datos reales con los que se trabajó y de cómo se cruzan los comprobantes con el extracto del banco. La versión corta está en el [README](../README.md).
>
> Las tablas de esta página son las de la **herramienta de medición** (`web/`, base `conciliador`). Las del producto están en [portal.md](portal.md).

# El modelo de datos

**PostgreSQL 18, nueve tablas, SQL plano con `pg`.** Sin ORM, sin capa de repositorios: nueve
tablas no justifican una capa más de indirección. Las migraciones viven en `web/migraciones/`
y son el DDL autoritativo — lo que sigue sale de leerlas.

## El mapa de relaciones

```
                    ┌──────────┐
                    │  cuenta  │  las 3 cuentas del extracto
                    └────┬─────┘
             ┌───────────┼────────────────┐
             │           │                │
    ┌────────▼───────┐   │        ┌───────▼──────┐
    │ extracto_carga │   │        │  cbu_propio  │  (cuenta opcional)
    └────────┬───────┘   │        └──────────────┘
             │           │
        ┌────▼───────────▼───┐
        │    movimiento      │  una fila del Excel
        └──┬──────────┬───┬──┘
           │          │   │
   ┌───────▼──────┐   │   │    ┌──────────────┐
   │ conciliacion │◄──┘   │    │   corrida    │──┐ cambio_respecto_de
   └───────▲──────┘       │    └──────┬───────┘◄─┘  (auto-referencia)
           │              │           │
           │        ┌─────▼─────┐     │
           │        │ eleccion  │     │
           │        └─────▲─────┘     │
           │              │           │
        ┌──┴──────────────┴───────────▼──┐
        │          comprobante           │──────► extraccion
        └────────────────────────────────┘        (N por comprobante)
```

Dos ejes, y no se tocan:

- **El eje del dinero:** `cuenta → extracto_carga → movimiento`, y `comprobante → conciliacion`
  que los une.
- **El eje de la medición del modelo:** `corrida → extraccion → comprobante`. Existe solo para
  poder responder *"¿mejoró la IA entre una corrida y la siguiente?"*.

---

## 1. `cuenta` — las cuentas bancarias propias

Diseñada para N cuentas desde el día uno, aunque hoy sean tres.

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SMALLSERIAL` PK | |
| `nombre` | `TEXT NOT NULL UNIQUE` | El nombre de la hoja del Excel |
| `banco` | `TEXT` | **NULL a propósito:** el extracto no dice de qué banco es y no se inventa |
| `cbu` | `TEXT` | ⚠️ **En NULL en las tres.** Ver más abajo por qué esto rompe el motor |
| `alias` | `TEXT` | |
| `activa` | `BOOLEAN NOT NULL DEFAULT TRUE` | Para dar de baja una cuenta sin borrar su historia |

Se siembra en la migración 001 con las tres hojas del extracto.

> ⚠️ **`cuenta.cbu` en NULL es la causa de que el motor viejo no verifique nada.** `motor.ts`
> cruza el CBU del receptor del comprobante contra esta columna; sin el dato, todo cae en
> `no_verificable`. Es el comportamiento correcto —no se opina sin información— pero deja el
> tablero mudo. El dato lo tiene que cargar una persona.

## 2. `extracto_carga` — cada subida de un Excel

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `cuenta_id` | `SMALLINT NOT NULL` → `cuenta(id)` | De qué cuenta es esta carga |
| `archivo` | `TEXT NOT NULL` | |
| `hash_archivo` | `TEXT NOT NULL` | Detecta que se subió dos veces el mismo archivo |
| `subido_en` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `filas_leidas` / `filas_nuevas` / `filas_duplicadas` | `INTEGER NOT NULL` | El resultado de la importación, a la vista |
| `fecha_min` / `fecha_max` | `DATE` | **La cobertura temporal** |

**Por qué `fecha_min` y `fecha_max` son la columna más importante de esta tabla:** sin saber
qué período cubre el extracto, es imposible distinguir *"la transferencia no está"* de *"el
extracto no llega hasta esa fecha"*. Son el estado ❌ **sospechoso** y el ⚠️ **no verificable**,
y confundirlos es acusar a un cliente honesto.

## 3. `movimiento` — una fila del extracto

La tabla más grande: **2822 filas**.

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `cuenta_id` | `SMALLINT NOT NULL` → `cuenta(id)` | |
| `carga_id` | `INTEGER NOT NULL` → `extracto_carga(id)` | De qué subida vino |
| `fecha` | `DATE NOT NULL` | |
| `nro_transaccion` | `TEXT` | **No es clave:** 1309 presentes, 1286 distintos |
| `descripcion` | `TEXT NOT NULL` | El texto crudo del banco |
| `importe_crudo` | `TEXT NOT NULL` | El texto tal como vino: `$ 368.500,00` |
| `importe` | `NUMERIC(14,2)` | **Nunca `float`.** NULL en las filas ambiguas |
| `es_ingreso` | `BOOLEAN NOT NULL` | El signo se conoce aunque el importe sea ilegible |
| `requiere_revision` | `BOOLEAN NOT NULL DEFAULT FALSE` | |
| `cuit_emisor` | `TEXT` | Parseado de la descripción. **La clave de cruce principal** |
| `coelsa_id` | `TEXT` | Solo en el 3% de las filas, pero cuando está es certeza |
| `tipo` | `TEXT` | |
| `huella` | `TEXT NOT NULL UNIQUE` | `hash(cuenta, fecha, nro, importe_crudo, descripcion)` |
| `hoja` / `fila` | `TEXT` / `INTEGER` | De qué pestaña y fila del `.xlsx` salió (migración 005) |

Tres decisiones que vale la pena entender:

**`importe_crudo` y `importe` conviven.** El Excel trae dos formatos de número mezclados en la
misma columna (`$ 368.500,00` argentino y `$ 16,000.00` norteamericano). Un parser ingenuo lee
el primero como 368,50 y descuadra todo **en silencio**. Guardar el texto original permite
auditar cualquier importe sin volver al Excel.

**La base impide que un importe fantasma llegue a la conciliación:**

```sql
CONSTRAINT importe_nulo_solo_si_se_revisa
  CHECK (importe IS NOT NULL OR requiere_revision)
```

Un importe se puede desconocer, pero solo si la fila está marcada para que una persona la mire.
No se adivina.

**`huella UNIQUE` es lo que hace idempotente la importación.** El Excel es un pegado manual de
descargas superpuestas y trae 21 pares de filas 100% idénticas. La huella las descarta sola, y
reimportar el mismo archivo dos veces es seguro.

**`SALDO` no está.** Es el saldo de la cuenta al momento: información del banco, no del
proyecto. Se lee del Excel y se descarta.

**`hoja` y `fila` existen porque estimarlas fallaba.** Antes se calculaban contando movimientos
de la cuenta, y la estimación se corre un lugar por cada fila que el Excel trae y la base no.
Medido: la fila mostrada estaba mal en 1196 de 1298 en una hoja, con desvíos de hasta 11 filas.

## 4. `comprobante` — la imagen que manda el cliente

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `archivo` | `TEXT NOT NULL` | |
| `hash_imagen` | `TEXT NOT NULL UNIQUE` | **Detecta el reenvío de la misma imagen** |
| `subido_en` | `TIMESTAMPTZ` | |
| `origen` | `TEXT CHECK ('manual', 'ia')` | Cómo se cargaron los campos |
| `estado_extraccion` | `TEXT CHECK ('pendiente','extraido','confirmado','error')` | |
| **los 16 campos** | ver abajo | **La verdad, corregida por una persona** |
| `revisado_en` | `TIMESTAMPTZ` | NULL = todavía nadie lo miró (migración 003) |
| `corrida_base` | `TEXT` → `corrida(nombre)` | Qué corrida sembró estos campos (004) |
| `formato_aceptado_en` | `TIMESTAMPTZ` | "Ya lo miré: el comprobante dice eso" (007) |

Los 16 campos, cada uno en su columna:

```
tipo_operacion  monto  moneda  fecha  hora
nombre_emisor   cuit_emisor    cbu_cvu_emisor    banco_emisor
nombre_receptor cuit_receptor  cbu_cvu_receptor  banco_receptor
concepto  referencia  coelsa_id
```

**Por qué 16 columnas tipadas y no un JSON:** se consultan de a una en la conciliación, y
`monto NUMERIC(14,2)` y `fecha DATE` dejan que la base valide lo que un JSON aceptaría mudo.

**`formato_aceptado_en` existe por un problema real.** `/revisar` marca los comprobantes cuya
verdad tiene forma imposible: un CUIT que no da 11 dígitos, un CBU que no da 22, o el texto
`"null"` guardado como valor. Sobre 51 revisados, 22 quedaron marcados — y entre ellos había
errores de verdad (9 CUIT de receptor mal, uno con un CBU en el campo del CUIT). Pero un largo
raro **no siempre es un error**: si el comprobante muestra el número enmascarado, lo guardado
es exactamente lo que hay que guardar. Sin esta columna esos casos quedarían marcados para
siempre y la lista de "con dudas" nunca llegaría a cero, que es lo único que la hace útil.

## 5. `conciliacion` — el veredicto

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `comprobante_id` | `INTEGER NOT NULL` → `comprobante(id)` `ON DELETE CASCADE` | |
| `movimiento_id` | `INTEGER` → `movimiento(id)` | La fila del extracto que lo respalda |
| `movimiento_pretendido` | `INTEGER` → `movimiento(id)` | Con qué chocó un duplicado (002) |
| `estado` | `TEXT CHECK (5 valores)` | `verificado, sospechoso, no_verificable, duplicado, ambiguo` |
| `confianza` | `TEXT CHECK ('alta','media','baja')` | |
| `regla` | `SMALLINT` | Qué escalón de la cascada lo resolvió |
| `decidido_por` | `TEXT CHECK ('motor','persona')` | |
| `decidido_en` | `TIMESTAMPTZ` | |
| `candidatos` | `INTEGER[] NOT NULL DEFAULT '{}'` | Los movimientos posibles de un ambiguo (002) |
| `nota` | `TEXT` | |

**Acá vive la defensa contra el doble cobro, y no depende de que el código se acuerde:**

```sql
CREATE UNIQUE INDEX conciliacion_movimiento_unico
  ON conciliacion (movimiento_id) WHERE movimiento_id IS NOT NULL;
```

Un movimiento del banco no puede ser reclamado por dos comprobantes. Es un índice único
parcial, no una validación en TypeScript: la base lo garantiza aunque el código tenga un bug.

Ese mismo índice obliga a que exista `movimiento_pretendido`: cuando un comprobante duplicado
choca contra un movimiento ya tomado, no puede apuntarlo con `movimiento_id` —el índice se lo
impide— y sin esta segunda columna no podría decir con qué chocó.

Dos `CHECK` más, que cierran estados imposibles:

```sql
CHECK ((movimiento_id IS NULL) = (confianza IS NULL))   -- si señala una fila, dice con qué confianza
CHECK ((estado = 'ambiguo') = (cardinality(candidatos) > 1))  -- un ambiguo sin candidatos no existe
```

Y un índice único por comprobante: **un comprobante tiene UN veredicto vigente**, no un
historial. Sin eso, cada corrida del motor apilaría una fila más.

**`sin_comprobante` no está en el `CHECK` a propósito:** es un estado del *movimiento*, no del
comprobante, y sale de una query (ingresos que ninguna conciliación referencia). El criterio
se repite en todo el esquema: **no se guarda lo que se puede preguntar.**

## 6. `corrida` — un experimento del modelo

Una corrida = un modelo + un prompt + (quizá) un adaptador LoRA.

| Columna | Tipo | Para qué |
|---|---|---|
| `nombre` | `TEXT` PK | `lora_v4_final`, `base_v1`, `sintetico`… |
| `descripcion` | `TEXT NOT NULL` | |
| `modelo` | `TEXT NOT NULL` | |
| `prompt` | `TEXT` | |
| `adaptador` | `TEXT` | La ruta del LoRA, si lo usa |
| `cambio_respecto_de` | `TEXT` → `corrida(nombre)` | **Auto-referencia: el linaje** |
| `que_cambio` | `TEXT` | |
| `creado_en` | `TIMESTAMPTZ` | |

**`cambio_respecto_de` + `que_cambio` son el linaje del experimento.** Un número sin la
explicación de qué se cambió no sirve para decidir nada: "81,7%" no dice nada si no se sabe
contra qué y cambiando qué variable. Hay **10 corridas** cargadas con **279 extracciones**.

## 7. `extraccion` — lo que contestó el modelo, crudo

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `comprobante_id` | `INTEGER NOT NULL` → `comprobante(id)` `ON DELETE CASCADE` | |
| `corrida` | `TEXT NOT NULL` → `corrida(nombre)` | |
| `campos` | `JSONB NOT NULL` | Los 16 campos tal como los devolvió el modelo |
| `segundos` | `NUMERIC(8,2)` | Cuánto tardó |
| `creado_en` | `TIMESTAMPTZ` | |
| | `UNIQUE (comprobante_id, corrida)` | Una extracción por comprobante y corrida |

**Esta es la tabla que hace posible medir, y su regla es una sola: nunca se corrige.**

La corrección humana vive en las columnas tipadas de `comprobante`; acá queda lo que el modelo
dijo, para siempre. Si se pisara, corregir un campo destruiría la evidencia de que el modelo lo
había sacado mal y no habría contra qué medir.

**Qué campos estaban mal no se guarda en ningún lado**: sale de comparar las dos.

```sql
SELECT id FROM comprobante
WHERE revisado_en IS NOT NULL
  AND monto::text IS DISTINCT FROM (extraccion_ia->>'monto');
```

Es la misma idea que `sin_comprobante`, aplicada a la medición.

> Nota de historia: la migración 003 guardaba una sola extracción en
> `comprobante.extraccion_ia`. Alcanzaba para corregir, pero no para comparar corridas. La 004
> migró ese contenido a esta tabla y **eliminó la columna**: dos lugares con la misma verdad es
> como se cuelan los errores silenciosos.

## 8. `cbu_propio` — los CBU/CVU que son nuestros

| Columna | Tipo | Para qué |
|---|---|---|
| `id` | `SERIAL` PK | |
| `cbu` | `TEXT NOT NULL UNIQUE` | Con `CHECK (cbu ~ '^[0-9]{22}$')` |
| `cuenta_id` | `SMALLINT` → `cuenta(id)` | **Opcional:** se puede aprobar sin saber a cuál va |
| `nota` | `TEXT` | |
| `agregado_en` | `TIMESTAMPTZ` | |

**Por qué no alcanza `cuenta.cbu`:** es uno por cuenta, y una cuenta tiene más de uno (CBU y
CVU, o cuentas viejas). Medido sobre 51 comprobantes revisados: hay 43 con CBU de receptor y
**solo 6 valores distintos**. La plata entra siempre a las mismas cuentas, así que un CBU de
receptor que no esté en esta lista es casi siempre un dígito mal leído por la IA — y un dígito
mal leído en un CBU **no se nota mirando**.

⛔ **La tabla se siembra vacía a propósito.** Que la IA haya leído el mismo número 20 veces no
lo hace correcto: si leyó mal un dígito en 20 comprobantes del mismo banco, sembrarlo
convertiría el error en la regla. Los aprueba una persona de a uno en `/cbu`, que los muestra
con su frecuencia para que se decida mirando.

## 9. `eleccion` — qué fila eligió una persona ⚠️ temporal

| Columna | Tipo | Para qué |
|---|---|---|
| `comprobante_id` | `INTEGER` PK → `comprobante(id)` `ON DELETE CASCADE` | |
| `movimiento_id` | `INTEGER NOT NULL` → `movimiento(id)` | Con `UNIQUE INDEX` |
| `elegido_en` | `TIMESTAMPTZ` | |
| `nota` | `TEXT` | |

`/encontrar` propone una fila del extracto por comprobante. Cuando hay más de un candidato no
elige ninguno —adivinar entre dos movimientos del mismo importe sería inventar— y acá se guarda
cuál eligió una persona. Con eso se mide lo único que importa mientras se desarrolla la regla:
**cuántas veces el algoritmo acierta solo y cuántas hay que corregirlo.** Hay 37 elecciones
humanas cargadas.

**Por qué NO guarda lo que propuso el algoritmo:** es determinístico y se recalcula en cada
carga de la pantalla. Guardarlo lo dejaría congelado, y el día que se toque la cascada la fila
vieja seguiría afirmando lo que la regla decía antes.

**Por qué NO es la tabla `conciliacion`:** aquélla la escribe `motor.ts`, que hoy devuelve
`no_verificable` en todos por el CBU en NULL. Son dos algoritmos distintos y mezclarlos haría
imposible saber cuál produjo cada fila.

⚠️ **Es temporal a propósito.** Cuando `motor.ts` se reescriba con la cascada nueva, esta tabla
se va con un `DROP TABLE` y las decisiones humanas pasan a `conciliacion.decidido_por = 'persona'`,
que ya existe.

---

## Dos bases, a propósito

| Base | Qué tiene | Quién la toca |
|---|---|---|
| `conciliador` | Los 2822 movimientos reales + los comprobantes | La aplicación |
| `conciliador_test` | Datos fabricados y descartables | Solo `pnpm test` |

El `DATABASE_URL` de test está en el script `test` de `package.json`, a la vista: los tests no
llegan a la base real ni por accidente. Ninguna migración lleva `DROP TABLE`.

⚠️ **`pnpm db:migrar` no se puede correr sobre la base real.** Las migraciones 001 y 002 no son
idempotentes (`ADD COLUMN` pelado); de la 003 en adelante sí lo son. Para aplicar una nueva:

```bash
/Applications/Postgres.app/Contents/Versions/18/bin/psql -v ON_ERROR_STOP=1 \
  -d conciliador -f migraciones/00N_loquesea.sql
```

Y también sobre `conciliador_test`, o los tests corren contra un esquema viejo.

---

# Los datos reales

## Extracto del banco (`TRANSFERENCIAS.xlsx`)

Tres hojas = **tres cuentas bancarias distintas**. **2843 filas con contenido** entre
2026-02-23 y 2026-08-05, que dejan **2822 movimientos** una vez descartadas las repetidas
(2526 ingresos, 296 egresos).

Columnas: `FECHA | NRO TRANSACCION | DESCRIPCION | IMPORTE | SALDO`
(la columna `F` son anotaciones personales ajenas al proyecto — **se ignora**)

Lo que el análisis del archivo reveló, y que el importador tiene que manejar sí o sí:

| Hallazgo | Detalle | Consecuencia |
|---|---|---|
| **Dos formatos de número mezclados** | 2481 filas `$ 368.500,00` (AR) vs 332 filas `$ 16,000.00` (US), en la misma columna y guardadas como texto | Un parser ingenuo lee 368.500,00 como 368,50 y descuadra todo en silencio |
| **Un solo importe es irresoluble** | Una celda dice literalmente `############`. Como la columna es texto, ese `###` **es** el dato | Queda sin importe y marcada para revisar. No se adivina |
| **El SALDO no se usa** | Es el saldo de la cuenta al momento — información del banco | Se lee y se descarta. No se modela, no se muestra |
| **El ID COELSA está, pero poco** | 84 de 2843 filas (3,0%), siempre de 22 caracteres | Camino exacto cuando está; el 97% se cruza por otro lado |
| **El CUIT sí está casi siempre** | Embebido en la descripción, parseable en 90-93% según la hoja | **Es la clave de cruce principal** |
| **Los nombres vienen truncados** | 8-16 caracteres, cortados a mitad de palabra | Inservibles para matchear solos |
| **`NRO TRANSACCION` no es único** | 1309 presentes / 1286 distintos | No sirve como clave primaria |
| **Hay filas repetidas** | 21 pares 100% idénticos, saldo incluido | El Excel es un pegado manual de descargas superpuestas |
| **Los egresos vienen en negativo** | 296 filas | Solo se concilian los ingresos: quedan 2526 |
| **Las fechas son objetos `Date`** | Todas a medianoche UTC, no seriales de Excel | Se leen en UTC: un día corrido rompería la tolerancia |

## Comprobantes

**78 comprobantes** en la base: 58 reales + 20 sintéticos.

**Los reales revisados a mano son lo más valioso del proyecto.** Sin ellos no se mide un solo
acierto, y rehacerlos cuesta horas de una persona. Se corrigieron campo por campo en `/revisar`,
y el repaso completo encontró errores en la propia verdad de referencia (9 CUIT de receptor mal,
uno con un CBU en el campo del CUIT). Al cerrar el repaso: **0 CUIT fuera de 11 dígitos, 0 CBU
fuera de 22**.

Provienen de otra fuente y de otro período que el extracto, así que **24 de ellos no cruzan con
este Excel**: sirven para medir la extracción de la IA, no para probar la conciliación.

> ✅ **La duda del "¿58 o 62 revisados?" está cerrada (2026-08-15): los dos números son
> correctos y miden cosas distintas.**
>
> ```sql
> revisado_en IS NOT NULL                                   -- 62  (incluye 4 sintéticos)
> revisado_en IS NOT NULL AND corrida_base <> 'sintetico'   -- 58  (los reales)
> ```
>
> El segundo es el filtro que usa `reales.py` para armar el dataset, y **58 es el número que
> hay que reportar** cuando se habla de la verdad de referencia.

---

# Cómo se cruzan las dos fuentes

Hay **dos cascadas** en el código, y conviene no confundirlas.

## La que funciona: `/encontrar`

Vive en `lib/eleccion.ts:candidatos()`. Es la que pidió la empresa.

```
1. nro de transacción + CUIT      → 90%
2. CUIT + monto + fecha           → 90%
3. monto + fecha                  → 50%
```

**El CUIT se compara por sus dígitos, no como texto.** El extracto lo trae sin separadores y una
persona lo escribe con guiones; compararlos tal cual dejaba **33 comprobantes sin poder cruzar
nunca**. Al plegar los guiones, los del 90% pasaron de 4 a 26 y los ambiguos de 9 a 3.

**Medida contra 37 elecciones humanas: 29 de 30 correctas cuando propone un solo candidato
(96,7%).**

Descartados **con medición**, no por opinión: un escalón `CUIT + monto` sin fecha (mete 14
ambiguos) y una ventana de fecha de ±3 días.

## La vieja: `motor.ts` ⚠️ con 3 agujeros abiertos

Cruza por `cuenta.cbu`, que está en NULL en las tres cuentas: **hoy devuelve `no_verificable` en
todo y no verifica nada.** No es un bug, es la consecuencia correcta de que falte el dato.

Sus tres agujeros de diseño, en orden de gravedad:

1. **No mira la moneda.** Un comprobante en dólares puede dar match falso contra un extracto en
   pesos. El más grave.
2. **`cbu_cvu_receptor` no alcanza como identificador.** Hace falta la cascada CBU → CUIT →
   nombre, y el CUIT de cada cuenta.
3. **Los CBU de las 3 cuentas siguen en NULL.**

Los tres se resuelven en la reescritura con TDD que absorbe la cascada de `/encontrar`.

## La regla que no se negocia

**Un movimiento del banco solo puede ser reclamado por un comprobante.** Si dos comprobantes
apuntan al mismo movimiento, ambos quedan marcados como duplicado. Es la defensa contra el
reenvío del mismo comprobante para dos pagos distintos, y la garantiza un índice único en la
base, no el código.

⛔ **Lo que se decidió NO hacer: forzarle una fila del extracto a un comprobante que no la
tiene.** Una coincidencia de importe a 100 días no es la misma transferencia. Ya pasó al revés
—19 cruces por monto+fecha, **0 sobrevivieron al chequeo de CUIT**—, que es exactamente por qué
la regla mira el CUIT antes que el importe.

---

