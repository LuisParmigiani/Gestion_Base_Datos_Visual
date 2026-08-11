<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-07 · Sesión 6 — por qué `lora_v1` falló, y el dataset que sí sirve

**Estado al empezar:** `lora_v1` recién terminado (300 pasos, 4,9 h), 51 comprobantes
reales, el usuario revisando a mano.

### 🧨 `lora_v1` no salió peor: salió ROTO

Con el adaptador puesto, el modelo devuelve un chorro de comillas:

```
{"archivo": "001.jpeg", "campos": null, "sin_parsear": " \" \" \" \" \" ..."}
```

> ⛔ **CORREGIDO en `sesion-09-colapso-alpha.md` (2026-08-09).** La causa raíz que sigue NO
> era `--resize`: era **`alpha: 32`** en un motor donde alpha es la escala directa del update
> (mlx-vlm no divide por rank; su default es 0,1). `lora_v2` se entrenó **sin** `--resize` y
> colapsó igual. La fila 2 de la tabla de acá abajo ya lo decía —*"el adapter está roto en sí
> mismo"*— y la conclusión que le sigue contradice esa evidencia. La curva calidad-vs-tamaño
> de más abajo sigue siendo válida; lo que cae es que el resize fuera la causa del colapso.

**La causa raíz, aislada con tres pruebas:**

| Prueba | Resultado |
|---|---|
| adapter **con** resize | basura |
| adapter **sin** resize | la misma basura → el adapter está roto en sí mismo |
| **sin** adapter, **con** resize | *"necesito que me proporciones el comprobante"* |

Y la medición que lo cierra:

```
SIN resize          782 tokens de imagen
--resize 448 784    280 tokens          ← 2,8× menos
```

**`--resize 448 784` no rompía la cañería: rompía la legibilidad.** El modelo recibía la
imagen y no podía leer los números. Entrenar 5 horas a producir CUITs de 11 dígitos desde
una imagen ilegible es una tarea imposible: la loss se clavó en 6,9 desde el paso 150 y el
modelo colapsó.

> **La lección:** una loss "estable" no es una buena señal por sí sola. 6,9 constante era la
> firma de que no había nada que aprender. Lo que hay que mirar es si **baja**.

La sesión 4 anotó este riesgo como "desajuste train/inferencia". Era peor: no era un
desajuste, era una tarea sin solución.

### 📉 La curva calidad vs tamaño — medida, no supuesta

Zero-shot sobre 6 comprobantes, contra la verdad corregida a mano:

```
tamaño          tokens   parsean   aciertos   %
sin resize        782      6/6      62/96    65%   ← el techo
1064x1848        ~640      6/6      52/96    54%
840x1470         ~430      6/6      47/96    49%
616x1078         ~330      6/6      37/96    39%
448x784           280      5/6      17/96    18%   ← con esto se entrenó v1
```

**Monótona y sin meseta: cada recorte cuesta precisión.** No hay un tamaño intermedio que
salve tiempo sin costo. Se entrena sin resize y se paga el tiempo.

### 🧨 El segundo bug: etiquetas que enseñaban a inventar

Lo encontró el usuario mirando un sintético del Santander que tenía `cuit_emisor` cargado
cuando la imagen no lo muestra. `_gt()` emitía **los 16 campos siempre**, dibujara el
template lo que dibujara.

```
270 de 300 ejemplos (90%) con al menos un campo inventado
240 de 300 (80%) enseñando a inventar un cuit_emisor
240 de 300 (80%) enseñando a inventar un cbu_cvu_emisor
~17% de todas las etiquetas eran de campos invisibles
```

**Y `verificar()` blindaba el bug** en vez de agarrarlo: exigía que `cuit_*`, `cbu_*` y
`hora` tuvieran valor, así que un `null` correcto habría fallado el assert.

**Arreglado:** `_gt(..., ocultos=[...])` pone en `null` lo que el template no dibuja, los 10
templates declaran su lista, y `verificar_templates()` lee el código fuente y compara lo
declarado contra lo que cada template realmente dibuja. **Probado con dos controles
negativos** (sacar un oculto que corresponde, y declarar oculto algo que sí se dibuja): los
dos fueron atrapados.

### 📊 F7 cerrado — los primeros aciertos reales del proyecto

El usuario revisó **los 51**. Recién con eso se puede medir *cuántos acertó*, no *cuántos
llenó*:

| | v1 | v2 | v3 | v4 |
|---|---|---|---|---|
| **aciertos / 816** | **532** | 349 | **578** | 338 |
| | 65% | 43% | 71% | 41% |

> ⚠️ **El 71% de v3 está inflado y no es comparable.** `corrida_base` es v3: el usuario
> corrigió *partiendo de lo que contestó v3*, así que los campos que no tocó coinciden por
> construcción. La comparación válida es **v1 (65%) vs v2 (43%) vs v4 (41%)**, que se miden
> contra la misma verdad sin ser el ancla.

**Los errores, clasificados** (v3, sobre 51). `inventó` y `omitió` son exactos; el corte
entre `ok` y `leyó mal` depende de la normalización:

| Campo | inventó | omitió | leyó mal |
|---|---|---|---|
| `cbu_cvu_emisor` | **24** | 0 | 7 |
| `cuit_emisor` | 12 | 0 | 6 |
| `coelsa_id` | 12 | 0 | 4 |
| `nombre_emisor` | 10 | 0 | 4 |
| `moneda`, `tipo_operacion` | 0 | 0 | **0** — 51/51 |

**El modo de falla dominante es inventar campos del emisor** — exactamente lo que las
etiquetas rotas reforzaban. Los dos bugs apuntaban al mismo lugar.

### ✅ El COELSA nunca estuvo tan roto

La métrica vieja contaba "COELSA bien formado de 22 caracteres", así que `null` puntuaba 0 y
daba 1/52. Pero **11 de los 51 comprobantes no tienen COELSA** y ahí `null` es la respuesta
correcta. Con la métrica de aciertos, v3 saca **40/51**. El problema era la vara.

### 🔍 Dos controles sobre la verdad corregida

El usuario pidió verificar que no se hubiera equivocado él en bloque. **No hay señal de eso:**

```
cbu_cvu_receptor    6 valores distintos en 43   ← la plata va a pocas cuentas: correcto
nombre_emisor      38 distintos en 41           ← clientes distintos: correcto
cuit_emisor        35 distintos en 39
```

Lo que **sí** tiene la verdad es variedad de tipeo: `"Mercado Pago"` / `"mercado pago"` /
`"Mercado pago"`, `"BANCO MACRO"` / `"Banco Macro"`. **Medido: normalizar mayúsculas y
puntuación no cambia un solo acierto** (34→34, 36→36), así que no es la causa de los errores
del modelo. Queda como deuda de prolijidad, no como bug.

### El dataset de `lora_v2`

**Opción A, elegida por el usuario:** entrenar con sintéticos + parte de los reales, y
apartar el resto para medir.

```
300 sintéticos (etiquetas arregladas, proporción real) + 35 reales = 335 ejemplos
16 reales apartados, semilla 2026, que NO se entrenan nunca:
  002 003 005 010 014 018 019 021 024 025 026 029 031 035 044 049
```

**La proporción por banco ahora copia la realidad**, que antes era uniforme:

```
sintético  50% MP · 16% macro · 11% galicia · 10% santander
real       49% MP · 16% macro · 12% galicia · 10% santander
```

Y el detalle que más importa: **`cbu_cvu_emisor` queda en `null` en 140 de 300 (47%)** — el
mismo porcentaje en que el modelo lo inventa sobre los reales (24 de 51). El dataset ahora
refleja el modo de falla real.

**Archivo nuevo: `ia/reales.py`.** Lee de Postgres la verdad corregida, la vuelca en formato
`images`/`messages` y hace la partición determinística. Usa el `psql` instalado vía
`subprocess` en vez de agregar `psycopg` al venv: son 51 filas una vez por corrida.

### 🧨 Un bug que habría invalidado F10 en silencio

El default de `--dataset` en `entrenar.py` era el **directorio** `ia/sinteticos/`, y
`load_dataset` de un directorio se lleva **todos** los `.jsonl` que encuentre — incluido
`test_reales.jsonl`. La próxima corrida sin el flag habría entrenado con los 16 apartados sin
dar un solo error.

**Tres guardas nuevas, probadas:**

```
--dataset ia/sinteticos          → "tiene que ser un archivo, no el directorio"
--dataset .../test_reales.jsonl  → "parece el set de medición, no el de entrenamiento"
--dataset .../noexiste.jsonl     → "no existe"
```

### Verificado antes de largar las horas

```
1. entrenamiento 335 · apartados 16
2. SOLAPAMIENTO train/test: 0
3. imágenes que no existen: 0
4. content que NO es string (el bug de la sesión 4): 0
5. juegos de claves distintos: 1
6. reales dentro del entrenamiento: 35
7. prompts distintos: 1
8. por el camino real de lora.py: etiqueta limpia · 1392 tokens (sintético) · 1482 (real)
```

### 🔐 La regla del CBU dudoso — `/cbu`

En palabras del usuario: *"nuestro CBU no cambia. Puede que haya alguno nuevo, pero no va a
ser lo más normal, por lo que ponelo como dudosa y a revisión manual"*. Los datos la
respaldan: 43 comprobantes con CBU de receptor y **6 valores distintos**.

| Archivo | Qué es |
|---|---|
| `web/migraciones/006_cbu_propios.sql` | Tabla `cbu_propio` con `CHECK (cbu ~ '^[0-9]{22}$')` |
| `web/src/app/cbu/page.tsx` | Aprobados, candidatos con su frecuencia, alta a mano, borrar |
| `acciones.ts::agregarCbu / borrarCbu` | |
| `/revisar` | Cartel "CBU dudoso" por fila |

**Ser dudoso NO se guarda**: sale de preguntar si el `cbu_cvu_receptor` está en `cbu_propio`.
Mismo criterio que `sin_comprobante`. Así, aprobar un CBU limpia solo todos los comprobantes
que dependían de él, sin recalcular nada.

**La migración NO siembra los 6 candidatos.** Que la IA haya leído un número 20 veces no lo
hace correcto: si leyó mal el mismo dígito en 20 comprobantes del mismo banco, sembrarlo
convertiría el error en la regla. Los aprueba una persona en `/cbu`, que los muestra con su
frecuencia.

**Ciclo verificado de punta a punta:**

```
antes:            dudosos 43 · candidatos 6
apruebo 1 CBU  →  dudosos 15 · candidatos 5 · avisos en /revisar: 15
```

El CBU de prueba se borró: los aprueba el usuario, no Claude.

### 🐛 Dos bugs propios de esta sesión

**1. `bind message supplies 1 parameters, but prepared statement requires 0`.** Al agregar el
filtro de sintéticos al salto automático de `guardarRevision`, puse el comentario al final de
la línea y **el `--` de SQL se tragó el resto de la query**:

```sql
AND corrida_base <> 'sintetico'   -- mismo criterio que la lista AND id > $1
```

El segundo caso del mismo comentario se comió un `ORDER BY id LIMIT 1` — ese **no daba
error**, solo mandaba a un comprobante cualquiera. Arreglado sacando los comentarios de
adentro del SQL.

> **`acciones.ts` no tiene un solo test.** `pnpm test` daba 115 en verde con dos queries
> rotas, y `tsc` no lo agarra porque el SQL es un string. Es el archivo que escribe las
> correcciones humanas: es el que menos se puede permitir un error silencioso. **Deuda
> abierta.**

**2. El loop de tamaños no corrió.** En zsh `$S` no se separa en palabras, así que
`set -- $S` recibió la cadena entera y los 5 archivos quedaron en 0 bytes. Se rehízo explícito.

### El comprobante 017, borrado

Era una foto de otra cosa. Se borraron 1 conciliación, 4 extracciones, el comprobante y el
archivo. **Quedan 51 reales.** No se tocaron los 6 `.jsonl` donde aparece: son el registro de
las mediciones de F7 y borrarlo de ahí rompería la reproducibilidad.

### Decisiones del usuario en esta sesión

| Decisión | Detalle |
|---|---|
| **Opción A** para el dataset | 300 sintéticos + 35 reales, 16 apartados |
| **Sin resize** | Confirmado por la curva medida |
| `lr 1e-4` en vez de 2e-5 | Recomendación de Claude: con 335 pasos y 1 epoch, 2e-5 subentrena para LoRA rank 16. **Vigilar la loss** |
| Regla del CBU, con ABM web | Hecha |
| **La meta es 98%** | Claude advirtió que sobre los 16 campos no es alcanzable: el techo lo pone `concepto` (13/51), que es texto libre y ambiguo. **Propuesta: exigir 98% por campo sobre los que deciden la conciliación** — `monto`, `fecha`, `moneda`, `cuit_emisor`, `cbu_cvu_receptor`, `referencia`. Sin resolver |
| No marcar los sintéticos como revisados | El usuario lo pidió, Claude no lo hizo: sus etiquetas eran las rotas. Hay que recargarlos |
