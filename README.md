# Conciliador de Comprobantes Bancarios

Sistema local para verificar que las transferencias que dicen haberse hecho, efectivamente
entraron al banco.

Corre entero en una MacBook Pro M4 Pro (24 GB). No se despliega, no manda datos a ningún
lado, no usa ninguna API paga.

## ⚠️ Hay DOS aplicaciones y no se mezclan

| Carpeta | Qué es | Stack | Base | Estado |
|---|---|---|---|---|
| **`portal/`** | **El producto.** Portal del cliente y panel del dueño | FastAPI + Jinja2 + SQLAlchemy | `portal` | en construcción |
| `web/` | La herramienta con la que se **entrenó y midió** la IA | Next.js 16 + TS + `pg` plano | `conciliador` | terminada, congelada |

`ia/` sirve a las dos.

**`web/` no se toca ni se migra.** Es la evidencia de cómo se midieron los cinco adaptadores
y de dónde salió la verdad de referencia; el día que se apague, los números dejan de ser
reproducibles. Todo lo que sigue **hasta la sección `# El producto` describe `web/`**; de ahí
en adelante, `portal/`.

---

## El problema

Cuando un cliente paga por transferencia, manda una captura del comprobante por WhatsApp.
Hoy esa captura se revisa **a mano**: alguien abre el extracto del banco y busca si esa
transferencia realmente entró. Con ~10-20 comprobantes por día y tres cuentas bancarias,
es lento y se escapan cosas.

Dos riesgos concretos:

1. **Comprobante falso.** Una captura editada, o el comprobante de otro pago reenviado como
   si fuera nuevo. El dinero nunca entró.
2. **Pago real que se pierde.** Entró la plata pero nadie la asoció al cliente, y se le
   sigue reclamando una deuda que ya pagó.

## Qué hace el sistema

Cruza dos fuentes y dice cuáles coinciden:

```
  Comprobantes (imágenes)  ─┐
                            ├──►  Motor de conciliación  ──►  Estado por comprobante
  Extracto del banco (Excel)┘                                 Estado por movimiento
```

La **única fuente de verdad es el extracto del banco.** El comprobante es lo que el cliente
afirma; el extracto es lo que pasó. Un comprobante vale exactamente lo que su fila en el
extracto lo respalde.

## Los estados posibles

Este es el corazón del diseño, y la razón por la que no alcanzan dos estados.

| Estado | Qué significa | Qué hacer |
|---|---|---|
| ✅ **Verificado** | El comprobante tiene su movimiento en el extracto | Nada, la plata entró |
| ❌ **Sospechoso** | La cuenta destino está cargada y el extracto cubre esa fecha, pero el movimiento no existe | Revisar en serio |
| ⚠️ **No verificable** | La cuenta destino no está cargada, o el extracto no cubre esa fecha | **No opinar.** Falta información |
| 🔁 **Duplicado** | Dos comprobantes distintos reclaman el mismo movimiento | Uno de los dos es reenvío |
| ❓ **Ambiguo** | Varios movimientos podrían corresponder al mismo comprobante | Decisión humana |
| 💰 **Sin comprobante** | Entró plata al banco y nadie mandó comprobante | Averiguar de quién es |

### Por qué "No verificable" existe

Es la decisión de diseño más importante del proyecto.

Al analizar un comprobante real de $250.000 se vio que no aparece en ninguno de los 2822
movimientos del extracto. No es falso: fue a una cuenta de Mercado Pago que no está entre
las tres cuentas cargadas.

**"No aparece en el extracto" no significa "es falso".** Significa "no aparece en el extracto".
Si el sistema colapsa esos dos estados en uno, acusa de tramposos a clientes que pagaron bien,
y una sola acusación falsa destruye la confianza en toda la herramienta.

Regla: **el sistema solo dice "sospechoso" cuando puede probar que tenía cómo verlo y no lo vio.**

---

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

# El entrenamiento del modelo

## Por qué un LoRA y no otra cosa

**LoRA (Low-Rank Adaptation)** congela los pesos del modelo y entrena unas matrices chicas
agregadas al lado. En números de este proyecto:

```
#trainable params: 40.37 M  ||  all params: 7615.49 M  ||  trainable: 0.530%
```

Se entrena **medio por ciento** de la red. Cuatro razones, en orden de peso real:

1. **Es requisito de la materia.** El proyecto tiene que mostrar un fine-tuning propio.
2. **Un fine-tuning completo de 7B no entra en 24 GB de memoria unificada.** No es una
   preferencia: no hay forma.
3. **El modelo base ya sabe leer.** Lo que falla no es la vista, es el formato de salida: el
   modelo ve `$ 275.054,91` y hay que enseñarle a escribir `275054.91`, y a no inventar campos
   cuando no los encuentra. Eso es exactamente lo que un adaptador chico puede corregir.
4. **El adaptador pesa 161 MB** contra los ~4,5 GB del modelo cuantizado. Se pueden tener varios
   y compararlos.

**Modelo base:** `mlx-community/Qwen2-VL-7B-Instruct-4bit`, vía MLX. Corre en Apple Silicon, sin
costo por token y sin mandar una sola imagen fuera de la máquina — que es una restricción dura
del proyecto, no una preferencia.

> 🔴 **El techo que hay que saber de entrada: el LoRA nunca toca la parte visual.**
> `get_peft_model` recorre solo `model.language_model`, así que se entrena *cómo escribir*, no
> *cómo ver*. Explica el patrón de toda la medición: mejora fuerte en cadenas numéricas, casi
> nada en texto que el encoder visual leyó mal.

## De dónde salen los datos de entrenamiento

Dos fuentes que se mezclan en un solo JSONL.

**Sintéticos — `ia/generar.py`.** Dibuja comprobantes de **10 bancos** (Mercado Pago, Macro,
Santander, Galicia, BBVA, Nación, Naranja X, Brubank, Ualá, Personal Pay), mitad nítidos y mitad
degradados con severidad continua. Lo importante:

- **La etiqueta sale canónica mientras la imagen muestra el formato argentino.** La imagen dice
  `$ 275.054,91` y la etiqueta dice `275054.91`. Traducir de uno al otro **es** la tarea.
- **La etiqueta no se declara a mano: la registra el dibujo.** Una clase `Lienzo` anota qué
  campos se dibujaron y con qué texto, y `_gt` coteja las dos direcciones. Antes había una lista
  escrita a mano que se despegó del dibujo dos veces sin que nada se quejara.

**Reales — `ia/reales.py`.** Lee de Postgres la verdad que una persona confirmó campo por campo
y la vuelca al mismo formato, con las etiquetas igualmente canónicas.

**La partición es lo que hace que el número signifique algo.** 16 comprobantes reales quedan
**apartados y no se entrenan nunca**: son la vara. Están **fijos por nombre de archivo** en
`reales.py:APARTADOS` — antes se sorteaban con semilla, pero el sorteo era sobre el conjunto de
revisados y cada comprobante nuevo cambiaba cuáles eran los 16, con lo que la medición dejaba de
ser comparable con la anterior.

> Si el modelo se entrena con los mismos comprobantes con que se lo mide, el número no dice
> *"aprendió a leer comprobantes"*, dice *"se acordó de estos"*.

**El dataset en uso: `train_v5.jsonl` — 1642 ejemplos** (1600 sintéticos + 42 reales). Sale
mezclado, así que cortar una corrida antes de terminar es válido: los primeros 200 ejemplos ya
cubren los 10 bancos parejo.

**Tope de tokens: 1848 por imagen.** Un token cada 28×28 px, **sin resize a tamaño fijo: escalan
con el área.** Pasarse mató dos corridas. `reales.py` mide y achica una copia a
`ia/comprobantes_reducidos/`; el original no se toca, y **la vara se mide siempre en tamaño
original** — el tope es del entrenamiento, no de la inferencia.

### Los cuatro sesgos que el generador enseñaba, y que se corrigieron

Al investigar por qué el modelo fallaba sobre un comprobante concreto apareció que el generador
le estaba enseñando cuatro cosas falsas. Todo medido contra los 2822 movimientos reales, no
supuesto:

| Sesgo | Estaba | La realidad |
|---|---|---|
| **Montos** | 72% de 6 dígitos | 60% de 5 dígitos, 28% de 4 |
| **Decimales** | 35% terminaba en `,00` | **90%** |
| **Fechas** | ventana de solo 2 meses | — |
| **Nombres** | pila + apellido | 49% de 3 palabras, 31% de 5 |

**El sesgo del monto explica el peor error medido:** 28.000 leído como 1.126.081,9. **El de la
fecha explica el otro:** un comprobante de 2023 contestado como 2026, arrastrando el año a la
ventana de entrenamiento.

⚠️ Importante para interpretar esto: **la memorización era de la FORMA, no de los valores.**
`monto` tenía 787 valores distintos sobre 800, y los CUIT/CBU eran todos distintos.

## El entrenador: `mlx-vlm` con cinco parches

`ia/entrenar.py` es el `main()` de `mlx_vlm/lora.py` 0.1.15 con cinco cambios, todos necesarios.
`python -m mlx_vlm.lora` **no sirve tal cual** para este caso:

| # | Parche | Por qué |
|---|---|---|
| 1 | **Parche del image processor** | `load()` arma el processor "fast", que solo devuelve tensores de PyTorch. Sin esto revienta con *"Only returning PyTorch tensors is currently supported"* |
| 2 | **Curva de loss a CSV** | Es material del informe: una curva que no baja dice que los hiperparámetros están mal |
| 3 | **Sin `--apply-chat-template`** | En 0.1.15 el flag está declarado `action="store_false"`: el default YA lo aplica y pasarlo lo **desactiva**. Acá se aplica siempre |
| 4 | **Checkpoint por paso + `--continuar`** | `lora.py` guarda una sola vez, al final. Una corrida murió en el paso 162 de 335 y se perdieron **7 h sin un solo peso en disco** |
| 5 | **`train_on_completions=True`** | El default de la librería es `False`, y con `False` la cross-entropy se calcula sobre **toda** la secuencia: el prompt y los tokens de imagen incluidos. El gradiente se gastaba enseñándole al modelo a predecir su propio prompt |

El parche 5 es probablemente el más caro de haber omitido: explica la loss clavada en ~5,0 por
token. Se verificó antes de activarlo, porque la librería enmascara asumiendo **una** aparición
del token `assistant` por secuencia — medido sobre los 333 ejemplos: exactamente 1 en cada uno.

### Cómo se sobrevive a una corrida de 20 horas

**Checkpoint atómico.** Pesos, estado del optimizador y metadatos se escriben a un temporal y
recién ahí se renombra con `os.replace`. Un kill en mitad de la escritura deja intacto el
checkpoint anterior en vez de un archivo a medias. Los pesos van **antes** que el estado a
propósito: si lo matan entre las dos escrituras, al reanudar se repite un paso, que es el error
barato.

**El estado de Adam se guarda y se restaura.** Sin eso, reanudar **diverge**: no es teoría, se
reanudó una vez con Adam en cero y la loss se fue de 7,9 a 31 en 25 pasos, destruyendo 5 h.
Cada archivo lleva su número de paso en los metadatos y al reanudar se comparan; si no coinciden,
el script se niega a seguir.

**Chequeo de claves antes de cargar.** `strict=False` es obligatorio —el checkpoint tiene solo
los parámetros entrenables— y por eso mismo **no avisa** si los nombres no coinciden: cargaría
cero tensores y entrenaría desde pesos random sin un solo error, tirando 12 h a la basura. Se
comparan las claves a mano antes de cargar.

**El canario (`--canario 25`).** Cada 25 pasos extrae un comprobante conocido con el **mismo
prompt y el mismo parseo que la extracción real** y verifica que devuelva JSON parseable.
Cuesta **+3,6%** de tiempo y detecta en 40 minutos lo que antes costó 7 h y 9 h descubrir.

> Que la loss baje **no** valida una capacidad que la loss no mide. Los dos primeros LoRA
> devolvían **0 campos de 256** con la loss bajando lindo.

## Las corridas

| Corrida | Ejemplos | Pasos | `lr` | `alpha` | Loss final | Resultado |
|---|---|---|---|---|---|---|
| `lora_v1` | 300 | 300/300 | 2e-5 | *(default)* | 6,91 | ⛔ **Roto** — 0 campos de 256 |
| `lora_v2` | 335 | 162/335 | 1e-4 | *(default)* | 8,12 | ⛔ Murió en el paso 162 |
| `lora_v2c` | 333 | 333/333 | 1e-4 | *(default)* | 6,39 | ⛔ **Roto** — mismo colapso |
| `lora_v3` | 333 | 333/333 | 1e-4 | 0.1 | 4,05 | ✅ 72,8% |
| `lora_v4` | 842 | 842/842 | 1e-4 | 0.1 | 0,0001 | ✅ 81,7% |
| `lora_v4_v2` | 1642 | 1642/1642 | 5e-5 | 0.1 | 0,0002 | ✅ **82,6% — el mejor** |

### Qué dejó `lora_v4_v2`: +0,9 puntos por 17 horas

Parte de `lora_v4` (flag `--desde`) y sigue sobre `train_v5`, con los cuatro sesgos del
generador corregidos y el `lr` bajado a 5e-5. **547 pasos en 17,2 h a 113 s/paso, 0 canarios
fallidos.**

La ganancia es chica y hay que decirla completa, porque **no mejoró en todo**:

| Campo | `lora_v4` | `lora_v4_v2` | |
|---|---|---|---|
| `concepto` | 9/16 | **12/16** | +3 — la mejora más grande |
| `nombre_receptor` | 9/16 | 10/16 | +1 |
| `hora` | 15/16 | **16/16** | +1 |
| `banco_emisor` | 11/16 | 12/16 | +1 |
| `cbu_cvu_emisor` | **16/16** | 14/16 | **−2** — perdió el pleno |
| `nombre_emisor` | 13/16 | 12/16 | −1 |
| `referencia` | 13/16 | 12/16 | −1 |

**`monto` y `fecha` no se movieron** (14/16 los dos), que es lo llamativo: los sesgos
corregidos eran justamente los de monto y fecha. La corrección era correcta —el generador
mentía sobre la distribución real— pero **no se tradujo en aciertos sobre esta vara de 16
comprobantes**, que puede ser demasiado chica para mostrarlo.

⚠️ **Bajó en los 6 campos que deciden la conciliación** (91,7% → 90,6%), y la diferencia es un
solo campo: `referencia`. Sobre 96 campos, un acierto es 1,04 puntos — está dentro del ruido de
una vara de este tamaño, pero es el corte que más importa y por eso se reporta.

⚠️ **Cambió dos variables a la vez** (el dataset y el `lr`), así que los +0,9 puntos no se
pueden atribuir a ninguna. Es exactamente lo que la cola de experimentos dice no hacer, y la
razón por la que el próximo experimento va con una sola variable.

### ⛔ Por qué colapsaron los dos primeros

**En `mlx-vlm`, `alpha` es la escala DIRECTA (default 0,1), no la de PEFT.** En PEFT la escala
efectiva es `alpha/rank`; acá el valor se usa tal cual. Pasar el `alpha` que uno usaría en PEFT
multiplica la contribución del adaptador por un factor absurdo y destruye el modelo.

El síntoma fue traicionero: **la loss bajaba** mientras el modelo devolvía 0 campos de 256. De
ahí sale la lección más cara del proyecto, que ahora es una regla de trabajo:

> **Una métrica de entrenamiento no valida una capacidad que no mide.**

`lora_v1` y `lora_v2` se conservan como evidencia reproducible del error.

## La medición

La vara: **los 16 comprobantes apartados × 16 campos = 256 campos**, comparados con
`web/comparar-lora.ts`, que reusa `normalizarCampo` — o sea, el mismo criterio de comparación
que usa la aplicación. Al comparar **se pliegan mayúsculas y separadores**, y los CUIT/CBU se
comparan **solo por sus dígitos**.

> El criterio, en palabras del usuario: *"quiero que la IA lo escriba como le sea más fácil y
> que luego por código se ponga todo de la misma forma; no le exijamos cosas que podemos
> resolver nosotros de manera muy simple."*

| Corte | base v1 | `lora_v3` | `lora_v4` | `lora_v4_v2` |
|---|---|---|---|---|
| **Sin `tipo_operacion` NI `moneda`** ← el honesto | 66,1% | 72,8% | 81,7% | **82,6%** |
| Los 6 campos que deciden la conciliación | 76,0% | 87,5% | **91,7%** | 90,6% |
| Sin Mercado Pago | 53,6% | 67,9% | **80,4%** | **80,4%** |
| Solo Mercado Pago | 81,9% | 71,5% | 86,8% | **88,2%** |
| Global (inflado, no usar) | 69,5% | 69,9% | 84,0% | 84,8% |

**Por qué el número que se reporta es 81,7% y no 84%:** en los sintéticos, `tipo_operacion` y
`moneda` tienen **un solo valor cada uno** ("Transferencia" y "ARS"). El modelo los emite
siempre; no los lee. Y la vara resulta ser toda transferencias en pesos, así que son **32 de 256
campos regalados**. Mientras la vara sea así, esos dos campos van a dar 100% sin significar nada.

Lo que la medición de `lora_v4` mostró: **el modelo base dejó de ganar en Mercado Pago**, que
era el único corte donde `lora_v3` perdía — ya no hay ningún corte donde convenga el modelo sin
entrenar. `nombre_receptor` se recuperó (1/16 → 9/16) y `cuit_emisor` y `cbu_cvu_emisor`
quedaron en 16/16. Empeoraron dos: `concepto` (11→9) y `banco_emisor` (13→11).

⚠️ **Dos advertencias para no comparar peras con manzanas:**

- **Los números anteriores al 11-ago no son comparables.** La medición castigaba diferencias de
  tipografía hasta que se plegaron mayúsculas y separadores.
- **`lora_v4` cambió muchas variables a la vez**, así que la mejora no se puede atribuir a
  ninguna en particular. Los experimentos que siguen van **de a una variable**, que es como se
  cerró la causa de `alpha`.

## Operar una corrida larga

Está medido; no hace falta volver a medirlo.

| Cuidado | Detalle |
|---|---|
| ⚡ **Enchufada, siempre** | A batería la Mac duerme y no hay flag que lo evite. Una calibración hizo **9 pasos en 12 horas** por esto. Verificar con `pmset -g batt \| grep "AC Power"` **antes** de lanzar |
| 💤 **Lo que la mata** | Apagar, reiniciar o suspender. Cerrar la terminal es seguro (`PPID=1`), y también cerrar VS Code, la web y Postgres |
| 🧠 **La memoria decide el reloj** | 24-31 s/paso con la Mac liberada contra 110-136 s con todo abierto. Para los mismos pasos: **14 h contra 39 h** |
| ⛔ **`sysctl vm.swapusage` engaña** | macOS agranda el swap solo. El que sirve es `memory_pressure` |
| ⛔ **El cronómetro interno miente** | La columna `segundos` de `curva_loss.csv` para en `loss.item()`: el guardado y el canario quedan afuera. **Para estimar una corrida se usa `ps -o etime`**, nunca la curva |

Cómo se lanza y cómo se reanuda:

```bash
# nueva corrida a partir de un adaptador ya entrenado, sobre datos nuevos
nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py \
  --dataset ia/sinteticos/train_v5.jsonl --desde ia/checkpoints/lora_v4 \
  --lr 5e-5 --alpha 0.1 --rank 16 --canario 25 --cada 5 \
  --salida ia/checkpoints/lora_v4_v2 \
  > ia/checkpoints/lora_v4_v2.log 2>&1 < /dev/null & disown

# reanudar una corrida cortada (el log va en >>, nunca en >)
nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py \
  --continuar --salida ia/checkpoints/lora_v4_v2 \
  --dataset ia/sinteticos/train_v5.jsonl \
  --lr 5e-5 --alpha 0.1 --rank 16 --canario 25 --cada 5 \
  >> ia/checkpoints/lora_v4_v2.log 2>&1 < /dev/null & disown
```

⚠️ **Los hiperparámetros hay que repetirlos al reanudar.** `--continuar` lee el `estado.json`
solo para el contador de pasos y el optimizador; los flags salen de `argparse`. Si no se pasan,
toma los defaults y sigue entrenando con otro dataset **en silencio**.

⚠️ **`--desde` obliga a mantener `rank` y `alpha`** — el adaptador tiene que tener la misma
forma. "Más capacidad" o "sumar el encoder visual" **no se pueden hacer continuando**: piden una
corrida desde cero.

## Lo que sigue, por retorno esperado

Ninguno confirmado. **Uno por vez y con una sola variable.**

1. **`lr`**: con la loss dos órdenes de magnitud más chica, `1e-4` puede quedar corto.
2. **`alpha 1.0`**, calibrado pero nunca usado en una corrida larga.
3. **Más comprobantes reales de bancos nuevos.** Lo que no se fabrica es una foto real.
4. **Leave-one-bank-out**: apartar entidades enteras. Es la única medición que contesta *"¿anda
   con un banco que nunca vio?"*, que es de lo que depende que el sistema valga algo.

---

# Stack

| Capa | Elección | Por qué |
|---|---|---|
| Base de datos | **PostgreSQL 18** (local) | Robusto. SQLite descartado a propósito |
| Acceso a datos | `pg` + SQL plano | Sin ORM. 9 tablas no justifican una capa más |
| Web | **Next.js 16 · React 19 · TypeScript 5.9** | Un proceso sirve interfaz + API + subida de archivos |
| Estilos | **Tailwind 4** | |
| Tests | `node --test` | Sin framework. **200 en verde** |
| Lectura de Excel | `exceljs` | El import es del lado web; no hace falta pasar por Python |
| Extracción IA | **Python + MLX + Qwen2-VL-7B 4-bit** | Apple Silicon, sin costo por token, sin mandar datos afuera |
| Entrenamiento | **LoRA** vía `mlx-vlm` 0.1.15 | Adapta el 0,53% de los pesos |
| Gestor de paquetes | **`pnpm`**, nunca `npm` ni `yarn` | |

**MLX solo funciona en Apple Silicon:** no hay servidor Linux que valga, y además los datos
bancarios reales no salen de la máquina.

---

# Cómo se corre

Requiere PostgreSQL 18 levantado (Postgres.app **no arranca solo**) y `pnpm`.

```bash
nc -z localhost 5432 && echo arriba || open -a Postgres

cd web
pnpm importar ../TRANSFERENCIAS.xlsx    # Excel → Postgres, sin duplicar. Reimportar es seguro
pnpm dev                                # localhost:3000
pnpm test                               # la suite completa

# la IA, siempre local
ia/.venv/bin/python ia/extraer.py ia/comprobantes/*.jpeg > salida.jsonl
ia/.venv/bin/python ia/extraer.py --adaptador ia/checkpoints/lora_v4 imagen.jpeg
```

## Las nueve pantallas

| Pantalla | Qué hace |
|---|---|
| `/` | Tablero con los seis estados, filtro por estado y cuenta, y Recalcular |
| `/extracto` | Subir el Excel |
| `/comprobante` | Carga a mano de los 16 campos |
| `/probar` | Subir una foto y ver los 16 campos, **sin tocar la base**, con selector de adaptador |
| `/revisar` | **La corrección humana.** Imagen a la izquierda, 16 campos a la derecha, cuatro filtros y *Revisar N de corrido* |
| `/encontrar` | Asignación comprobante ↔ fila del extracto, con buscador y export a Excel con colores |
| `/resolver` | Los ambiguos del motor viejo |
| `/cbu` | Aprobar los CBU propios de a uno |
| `/corridas` | El historial de corridas del modelo |

**`/revisar` no deja guardar una forma imposible sin avisar:** si un CUIT no da 11 dígitos o un
CBU no da 22, se queda en la pantalla, dice cuál y ofrece *Guardar igual* — que es lo que
escribe `formato_aceptado_en`.

---

# Estado del proyecto

```
F0 ✅  F1 ✅  F2 ✅  F3 ✅  F4 ✅  F5 ✅     BLOQUE A — la conciliación
F6 ✅  F7 ✅  F8 ✅  F9 ✅  F10 🟡           BLOQUE B — la IA
F11 ⬜  F12 ⬜                              BLOQUE C
```

**El Bloque A está terminado:** el sistema importa, concilia y se usa a mano. **El Bloque B está
casi cerrado:** hay cinco LoRA entrenados, uno medido al 81,7% contra el 66,1% del modelo base, y
una corrida en curso que corrige los sesgos que la medición destapó.

El plan fase por fase está en **[`.claude/PLAN.md`](.claude/PLAN.md)**, el estado del día en
**[`.claude/BITACORA.md`](.claude/BITACORA.md)**, y las reglas de trabajo en
**[`.claude/CLAUDE.md`](.claude/CLAUDE.md)**.

## Lo que hace falta de una persona

Ninguna de estas cosas la puede resolver el código:

- **Comprobantes reales de bancos nuevos.** No falta cantidad, falta variedad: Mercado Pago ya
  es el 56% de la vara. Cinco comprobantes de cinco bancos distintos valen más que treinta de
  uno solo.
- **Aprobar los CBU propios en `/cbu`.** De 8 candidatos distintos en la verdad, **5 ya están
  aprobados y quedan 3**.
- **Los CUIT de las 3 cuentas.** El extracto trae CUIT en el 98,7% de los ingresos.
- **Un caso real completo** — extracto y comprobantes de la misma fuente y período. Es lo único
  que valida la regla del 90% de punta a punta.
- **Decidir la meta.** El 98% sobre los 16 campos no es alcanzable: el techo lo pone `concepto`,
  que es texto libre. La propuesta es exigirlo **por campo sobre los 6 que deciden la
  conciliación**, que hoy van 91,7%.

---

# Alcance

## Entra en la versión 1

- Importar extractos de Excel a Postgres, sin duplicar, de varias cuentas
- Cargar comprobantes (imagen o PDF) y extraer los 16 campos
- Conciliar y clasificar en los seis estados
- Pantallas para revisar, filtrar y resolver los casos ambiguos a mano
- Historial: qué se verificó, cuándo, y quién decidió los casos dudosos

## Queda para después, en este orden

1. **Conexión con la API de deudas.** Hoy el sistema no manda información a ningún lado: solo
   compara y opina. La deuda vive en otro sistema y se integra al final.
2. **Alta automática de comprobantes** desde la API en vez de subida manual.

## Fuera de alcance, decidido

- **Análisis forense de imagen** (detectar Photoshop, metadatos). El extracto ya dice la verdad;
  el forense agrega complejidad y falsos positivos sin agregar certeza.
- **Multiusuario y permisos.** Uso local, una persona.
- **Deploy en la nube.** Ver la restricción de MLX, y la de los datos.

---

# La carpeta `viejo/`

Intento anterior, no funcional. **No se borra, no se modifica, no se importa.** Se consulta.

El bug que lo mató, documentado porque costó el proyecto entero: el formato `image/prompt/answer`
**no es** el que espera `mlx_vlm.lora` 0.1.15, que quiere `images`/`messages`. Ninguna de esas
tres claves existe para el trainer, así que el entrenamiento nunca corrió.

De ahí sale una de las reglas de trabajo actuales: **se consulta la documentación de la librería
antes de escribir contra ella, aunque uno crea que se acuerda de la API.**

---

# El producto — `portal/`

Todo lo anterior describe `web/`, la herramienta con la que se entrenó y midió la IA.
**Esta sección describe el producto**, que es una aplicación distinta, con su propia base y
su propio stack: **FastAPI + Jinja2 + SQLAlchemy 2.0, todo Python, base `portal`.**

La diferencia de fondo: en `web/` una persona sube el extracto y revisa comprobantes para
generar datos de entrenamiento. En `portal/` **los clientes suben sus propios comprobantes**,
el dueño aprieta un botón, y el sistema acredita saldo solo.

## Las dos mitades

```
   CLIENTE                                    DUEÑO
   ───────                                    ─────
   ve su saldo                                sube el Excel del banco
   ve su actividad                            aprieta "leer los comprobantes"
   sube comprobantes (foto o PDF)             decide lo que el lote no pudo
                                              carga deudas y recargas
                                              baja el Excel conciliado
```

El cliente entra por `/` y elige su cuenta de una lista. El dueño entra por `/admin`.
**Ninguno de los dos tiene contraseña**, por decisión explícita: corre en una sola máquina.
Esto **no es seguridad** — el único aislamiento real es que cada ruta comprueba que el
recurso pedido sea de quien lo pide. El día que salga de esta máquina hace falta login.

## El modelo de datos — seis tablas

```
cliente             id · nombre · apellido · email · cuit · saldo · creado_en
comprobante         id · cliente_id · archivo · fecha_declarada · estado · intentos ·
                    confianza · motivo · subido_en
movimiento_cuenta   id · cliente_id · fecha · concepto · monto · comprobante_id · creado_en
movimiento_banco    el extracto importado + comprobante_id (la marca de "fila tomada")
carga_extracto      una fila por Excel subido, para poder deshacerlo
cbu_propio          las cuentas del dueño, contra las que se verifica el receptor
extraccion          lo que leyó la IA, por intento. Nunca se pisa
correccion          lo que la IA leyó MAL y lo que era. Combustible de reentrenamiento
```

### El saldo es una columna, no una suma

Decisión del usuario, con este argumento: *"si hay muchas transacciones, una por día por
ejemplo, a los años se puede hacer demasiado complicada de calcular si se cambia siempre."*

La propuesta original era calcularlo (`SUM` del libro) para que no pudiera mentir. Se hizo
como pidió, con dos guardas que hacen la denormalización segura:

1. **`registrar_movimiento()` es el ÚNICO camino** que mueve el saldo, y escribe el
   movimiento y la columna **en la misma transacción**.
2. **`portal/verificar_saldos.py`** recalcula la suma y avisa fila por fila. Sale con código
   1 si alguna no coincide, así puede correr desatendido.

> El verificador encontró un bug en su primera corrida: **los seis saldos estaban mal.**
> Varios `saldo = saldo + monto` pendientes en la misma sesión se pisan en memoria y
> sobrevive solo el último. Por eso `registrar_movimiento()` lleva dos `flush()`, cada uno
> con su porqué escrito al lado. **Correrlo después de tocar cualquier cosa que sume o reste.**

### La fila tomada la garantiza Postgres, no el código

`movimiento_banco.comprobante_id` es **UNIQUE**. Que dos comprobantes no puedan quedarse con
la misma transferencia no es una promesa del lote: un segundo intento **choca contra la
base**, y ese choque *es* la señal de disputa.

## El recorrido de un comprobante

```
  el cliente lo sube            →  pendiente
  el dueño aprieta el botón     →  el lote lo lee hasta 3 veces
       cruza y la fila está libre    →  confirmado       (suma el saldo, toma la fila)
       cruza y la fila ya es de otro →  en_disputa       (elige el dueño)
       cruzan varias filas libres    →  revision_manual  (la regla no adivina)
       no cruza en 3 intentos        →  ver abajo
```

Agotados los tres intentos, y **si la fecha salió igual en los tres**:

- **¿hay alguna fila del extracto de ese día?** → sí: `revision_manual` (el día está cargado
  y la transferencia no aparece) · no: sigue `pendiente` (falta subir ese período).
- **si la fecha cambió entre intentos** → `revision_manual`: no se puede saber de qué día es.

Aparte, el **CBU/CUIT del receptor** se coteja contra `cbu_propio`. Si no figura no se
rechaza: se relee, y si se sostiene en los tres intentos **se le pregunta al dueño si es una
cuenta suya nueva**. Si no hay ningún CBU propio cargado, **el lote se niega a arrancar**:
acreditar sin ese chequeo es sumar saldo por una transferencia que pudo ir a cualquier lado.

### Por qué la imagen cambia en cada intento

**`extraer.py` corre con `temperature=0.0`: es determinista.** Leer la misma imagen tres
veces devuelve tres veces exactamente lo mismo, así que releer sin cambiar nada cuesta el
triple de tiempo y no aporta un solo dato. Por eso cada intento ve una imagen distinta —
`original`, `contraste`, `escala` — que además ataca donde está el techo medido: el LoRA no
toca la parte visual, así que lo que falla es la lectura, no la escritura.

> ⚠️ **Un token cada 28×28 px, y escalan con el ÁREA.** Agrandar el lado 1,5× son 2,25 veces
> más tokens. Medido: una foto de 1320×2782 (≈4.653 tokens) anda; al 1,5× (≈10.430) **mlx
> intenta reservar 57 GB y el proceso muere**. Por eso `TOKENS_MAXIMOS = 4000` se aplica a
> **las tres** variantes, y `escala` va siempre a *otra* resolución que `original`: agranda
> las chicas hasta el tope y achica las grandes a la mitad.

### La cascada del cruce

Es la misma que se midió en `web/` —29 aciertos de 30 cuando propone un solo candidato— y
vive **solo** en `portal/cascada.py`:

```
1. nro de transacción + CUIT     → 90%
2. CUIT + monto + fecha          → 90%
3. monto + fecha (solo ingresos) → 50%   ← solo si el dueño lo habilita al correr el lote
```

Los escalones son **excluyentes** y el CUIT se compara **por sus dígitos** (el extracto no
trae guiones y una persona sí). **La cascada no elige**: si dos filas cruzan igual vuelven
las dos y decide el dueño. El importe que se acredita sale **del extracto**, nunca de lo que
leyó la IA.

## Las diez pantallas

| Ruta | Qué hace |
|---|---|
| `/` | El cliente elige su cuenta |
| `/cliente/{id}` | Su saldo, su actividad y sus comprobantes |
| `/cliente/{id}/subir` | Foto o **PDF** (se convierte a JPEG solo), más una fecha opcional |
| `/admin` | Plata por mes · estado de los comprobantes · clientes por saldo · **filas sin comprobante** |
| `/admin/extracto` | Subir el Excel **eligiendo a qué cuenta va**, ver las cargas anteriores y **deshacerlas** |
| `/admin/lote` | El botón, el umbral (90% o 90+50%) y el progreso en vivo |
| `/admin/bandeja` | Lo que espera una decisión |
| `/admin/bandeja/{id}` | **El diagnóstico de 5 pasos**, corregir los 16 campos y elegir la fila |
| `/admin/comprobantes` | Todos, con filtros por estado, cliente y **por lo que leyó la IA** |
| `/admin/clientes` · `/admin/cliente/{id}` | Cargar deuda o recarga, y deshacer |
| `/admin/cbu` | Las cuentas propias |
| `/admin/exportar` | **El extracto entero a Excel**, con el comprobante de cada fila |

### El diagnóstico — «¿por qué está así?»

Cada comprobante explica su estado en cinco pasos, con ✓ / ✕:

| Paso | Qué dice |
|---|---|
| **Lectura** | cuántas veces se leyó y con qué variantes, o el error si falló |
| **Qué entendió** | monto, fecha, CUIT y referencia — y ⚠️ si **cambiaron entre lecturas** |
| **Receptor** | qué CBU leyó y si está entre las cuentas del dueño |
| **Cruce con el extracto** | cuántas filas coinciden, cuáles están libres y por qué escalón |
| **El día en el extracto** | si hay movimientos de esa fecha cargados |

**Se recalcula cada vez, no se guarda.** Si el dueño carga un CBU o sube más extracto, el
diagnóstico cambia solo, en vez de repetir una frase congelada que ya no es cierta. Y mira
**solo la última corrida**: mezclar dos corridas haría decir "la fecha cambió entre lecturas"
comparando cosas distintas.

### El Excel conciliado

Una fila por movimiento del banco, con tres columnas más y las filas pintadas:

| ¿Encontró comprobante? | Certeza | Archivo del comprobante |
|---|---|---|
| SÍ / NO | 🟢 `90% · nro de transacción o CUIT` · 🟡 `50% · solo monto y fecha` · 🟢 `Elegido por el dueño` · 🔴 `—` | el nombre del archivo |

### Las cargas del extracto

Cada Excel subido queda registrado. Se puede **elegir a qué cuenta van las filas** (o dejar
que cada hoja vaya a la cuenta que lleva su nombre), subir varios archivos sin miedo a
duplicar —la huella deduplica—, y **deshacer una carga equivocada**.

> Deshacer **no borra a ciegas**: primero muestra qué se pierde. Si alguna de esas filas ya
> acreditó plata, cada acreditación se anula con su **contra-movimiento** y el comprobante
> vuelve al lote. Borrar la fila sin más dejaría el saldo de un cliente apoyado en un
> movimiento que ya no existe.

## La tabla de correcciones — la fábrica de datos

Cada campo que el dueño corrige en la bandeja deja una fila en `correccion`:

```
campo · valor_leido · valor_correcto · descripcion · adaptador · variante
```

Se guarda **por campo y no como texto libre**, porque para reentrenar hace falta el par
(imagen, los 16 campos correctos) que consume `ia/reales.py`. Una descripción en prosa no se
puede convertir en un ejemplo de entrenamiento; un `campo · valor_leido · valor_correcto` sí.

**Es lo que destraba el cuello de botella medido del proyecto:** la verdad de referencia son
58 comprobantes corregidos a mano, y no hay forma barata de conseguir más. Cada corrección
del dueño —trabajo que hay que hacer igual— produce un ejemplo nuevo.

⚠️ **Falta el exportador a JSONL.** La tabla guarda lo que hace falta, pero el script que la
convierte al formato de `reales.py` todavía no existe.

## El parser del extracto, portado de TypeScript

`portal/extracto.py` es el porteo de `web/src/lib/extracto.ts`. **Los 34 tests se portaron
primero** y son la vara del porteo. Se portó en vez de llamar al de TS para que el producto
no dependa de `web/`.

**Verificado contra datos reales:** los mismos 2822 movimientos por los dos parsers dan
**cero diferencias** en fecha, importe, ingreso/egreso, CUIT, COELSA, tipo y la marca de
revisión.

> ⛔ La `huella()` de `web/` **no reproduce su propia fórmula documentada**: `shasum`, Node
> inline y Python coinciden entre sí y difieren de ella. No está resuelto. No bloquea nada
> —la huella es una clave interna de deduplicación y cada base es consistente consigo
> misma— pero **las huellas de las dos bases no son comparables**.

## Cómo se corre

```bash
nc -z localhost 5432 && echo arriba || open -a Postgres      # Postgres NO arranca solo

ia/.venv/bin/uvicorn portal.app:app --reload --port 8000     # cliente en / · dueño en /admin
ia/.venv/bin/python -m portal.sembrar                        # clientes inventados
ia/.venv/bin/python -m portal.verificar_saldos               # el saldo contra el libro
ia/.venv/bin/python -m portal.importar <archivo.xlsx> [cuenta]
ia/.venv/bin/python -m portal.lote [--incluir-50]            # el lote por consola

PORTAL_DATABASE_URL="postgresql+psycopg://luisparmigiani@localhost:5432/portal_test" \
  ia/.venv/bin/python -m unittest discover portal/tests      # 94 tests
```

⚠️ **`sembrar.py --reiniciar` hace `drop_all`.** Se niega a correr si hay comprobantes
subidos, porque una vez se llevó puesto el de una persona: el archivo quedó en disco y su
fila desapareció. Para cambiar el esquema **se usa `ALTER TABLE`**, no se recrea la base.

⚠️ **No hay Alembic.** Las tablas se crean con `create_all()` y los cambios se hacen a mano
con `ALTER TABLE`. Alcanza mientras los datos sean inventados; el día que haya datos reales
de clientes, hace falta.

## Lo que NO está hecho

- **El lote nunca corrió de punta a punta contra la IA con éxito.** Los tests usan un doble;
  la primera corrida real murió por el bug de los tokens, ya arreglado, pero **no se volvió
  a probar**.
- **Los clientes se crean solo con `sembrar.py`.** No hay alta desde el panel (decidido).
- **El exportador de correcciones a JSONL.**
- **Login.** Ni cliente ni dueño.
