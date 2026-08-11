<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-06 · Sesión 3 — arranca el Bloque B (IA)

**Estado al empezar:** Bloque A cerrado, 112 tests en verde, Postgres arriba, 2822 movimientos
en la base. Los 3 CBU seguían en NULL — el usuario los pidió y quedan pendientes de que se los
pasen. Se decidió arrancar el Bloque B sin ellos: **F6 no depende de los CBU**, son caminos
independientes (los CBU son de la conciliación, la IA lee campos de imágenes).

### El entorno de IA

```
ia/.venv/          Python 3.12.13
ia/comprobantes/   los 52 reales, COPIADOS de viejo/ y renumerados 001..052
ia/mapa_comprobantes.tsv   001.jpeg → nombre original de WhatsApp
```

Se **copiaron**, no se renombraron: `viejo/` es de solo lectura por regla del proyecto. Los
nombres originales (`WhatsApp Image 2026-06-16 at 11.54.45 (3).jpeg`) tienen espacios y
paréntesis que rompen rutas en scripts.

`mlx-vlm 0.1.15` · `mlx 0.29.3` · `transformers 4.57.6` · `torch 2.8.0` · `openpyxl 3.1.5`.
El modelo `mlx-community/Qwen2-VL-7B-Instruct-4bit` (4.4 GB) **ya estaba en el cache de HF**:
no hubo que descargarlo.

### Dos trampas de librería, confirmadas con evidencia

| Trampa | Qué pasó |
|---|---|
| **La doc de context7 no sirve para 0.1.15** | La rama `main` documenta `generate()` devolviendo un objeto con `.text`. En **0.1.15 devuelve un `str`**. Seguir la doc habría roto. Se verificó con `inspect.signature` contra la versión instalada — que es lo que la regla del proyecto manda |
| **El image processor "fast"** | `load()` arma el processor rápido, que solo devuelve tensores de PyTorch. Sin el parche falla con `ValueError: Only returning PyTorch tensors is currently supported`. **Se probó a propósito sin el parche primero**, para no arrastrarlo por inercia desde `viejo/extraer_datos.py`. Falló exactamente como estaba documentado. El parche se quedó, ya justificado |

### Lo que se construyó

| Archivo | Qué hace |
|---|---|
| `ia/extraer.py` | Inferencia local. Tres prompts (v1/v2/v3) seleccionables, todos reproducibles. Rescata JSON truncado |
| `ia/calidad.py` | Mide **formato** de una extracción y compara dos. **Nunca imprime un valor**, solo cuentas |
| `ia/validar.py` | Separa lo confiable de lo que no. No corrige ni adivina |
| `ia/planilla.py` | Genera el `.xlsx` de corrección humana, modo híbrido |

### Decisiones de esta sesión

| Decisión | Motivo |
|---|---|
| **Una sola corrida sirve para F6 y F7** | La salida cruda es a la vez el borrador a corregir (F6) y el grupo de control (F7). Condición: el crudo no se toca nunca |
| **Se itera el prompt ANTES de fijar el baseline** | Un baseline débil hace que el fine-tuning parezca mejor de lo que es. Mejorar el prompt primero es más riguroso, no menos. Sigue siendo zero-shot: no hay entrenamiento |
| **La planilla de F6 es híbrida** | Los 4 campos críticos van **en blanco** (tipeo independiente), los otros 12 precargados. Cuesta ~10 min más y evita el sesgo de anclaje donde más duele |
| **Se agregó `openpyxl`** | La stdlib escribe CSV, pero Excel convierte un CBU de 22 dígitos a notación científica y **corrompe el dato en silencio**. Ya estaba en el `requirements.txt` del intento anterior |
| **`*.jsonl` y `*.tsv` al `.gitignore`** | Las salidas de la IA llevan los 16 campos de comprobantes reales. Había un hueco: el `.gitignore` cubría imágenes y Excel, no estos |
| **Claude no mira los comprobantes** | Abrirlos mandaría datos bancarios reales a la nube (regla 2). Todo el análisis se hizo sobre **estructura**: largos, tipos, formatos y colisiones entre campos — nunca valores. La corrección de F6 la hace una persona, y además el plan ya lo exigía |

### Lo que se aprendió del modelo — medido sobre los 52

El zero-shot con el prompt del intento anterior (v1) parseó **52/52**, pero el contenido tenía
tres problemas que **no eran de visión sino de consigna**:

1. **`coelsa_id` prácticamente siempre mal** — 1 de 28 con los 22 caracteres correctos. 5 eran
   idénticos al campo `referencia` y 13 medían 18 chars: estaba metiendo el número de operación
   del banco en el campo del COELSA
2. **Escribía `"N/A"` en vez de `null`**, pese a pedírselo
3. **`monto` como texto en la mitad de los casos**, y `fecha` en `DD/MM/YYYY` 8 de 49 veces

**Un aprendizaje de prompting que vale anotar:** en v2 se escribió *"un CUIT tiene 11 dígitos y
un CBU tiene 22, no los confundas"* — y los CBU **empeoraron**, apareciendo 5 con largo 11.
Nombrar explícitamente una confusión puede inducirla. v3 sacó esa advertencia.

**Un error metodológico propio, corregido:** la primera comparación v1 vs v2 fue sobre 52 vs 44
comprobantes, porque 8 de v2 no habían parseado. Comparar sobre poblaciones distintas hacía
ver caídas que no existían. Se agregó el rescate de JSON truncado, se re-parseó, y recién ahí
la comparación fue sobre los mismos 52.

**Un segundo error propio, también corregido:** la primera regla de validación de `monto` exigía
que el JSON trajera un tipo numérico. v3 devolvía los 52 montos como string y la tabla marcó
`0/52 bien formado` — un falso negativo total. Los 52 strings eran convertibles sin ambigüedad
(44 con dos decimales, 8 enteros). La regla se reescribió replicando la de F2, incluido el caso
que **no se resuelve**: `"1.500"` puede ser mil quinientos o uno con cincuenta, así que devuelve
`None` y va a carga manual. Probada con 12 casos, los 12 pasan.

### Los tres prompts, medidos sobre los mismos 52

Campos que pasan validación, sobre 52 comprobantes:

| | v1 | v2 | **v3** | v4 |
|---|---|---|---|---|
| `monto` * | 45 | 52 | **52** | 52 |
| `fecha` * | 40 | 49 | 44 | **51** |
| `cuit_emisor` * | 34 | 38 | **39** | 32 |
| `coelsa_id` * | 1 | **4** | 1 | 1 |
| `cbu_cvu_emisor` | 30 | 23 | **30** | 28 |
| `cbu_cvu_receptor` | 35 | 29 | **34** | 3 |
| **TOTAL campos útiles** | 591 | 637 | **664** | 528 |

**Gana v3 y queda como baseline de F7.** Es el default de `extraer.py`. v4 se escribió después
de mirar los comprobantes reales y perdió por lejos — ver el bloque del ESTADO ACTUAL sobre
por qué, que es la lección más aprovechable de la sesión.

### 🔑 El hallazgo más importante: el motor solo mira 5 de los 16 campos

Verificado leyendo el `type Comprobante` de `web/src/lib/motor.ts`:

```typescript
monto:       string          obligatorio
fecha:       string          obligatorio
cbuReceptor: string          obligatorio  ← define a qué cuenta apunta
cuitEmisor:  string | null   opcional, habilita la regla 2
coelsaId:    string | null   opcional, habilita la regla 1
```

**Los otros 11 campos no cambian ni un veredicto.** Nombres, bancos, concepto, hora, moneda,
referencia, `cuit_receptor` y `cbu_cvu_emisor` son informativos.

Esto reordena todo el trabajo pendiente. Medido sobre los 52 con v3:

```
31/52  se pueden cruzar contra el extracto tal como están
21/52  no — y a 16 de esos les falta UN SOLO campo

falta cbu_cvu_receptor en 18/52   ← el único cuello de botella real
falta fecha            en  8/52
falta monto            en  0/52
```

El usuario confirmó que **no todos los comprobantes traen COELSA**, así que ese campo deja de
ser una alarma: su ausencia es correcta y no frena nada.

**Error propio corregido:** `validar.py` tenía como obligatorios solo `monto` y `fecha`.
Faltaba `cbu_cvu_receptor`, que es el que el motor usa para encontrar la cuenta. Sin él el
veredicto es `no_verificable` aunque el movimiento esté en el extracto.

### ⚠️ Se levantó la regla 2 para tres comprobantes

El usuario **autorizó explícitamente** a mirar los comprobantes reales, después de que se le
explicara dos veces que Claude corre en la nube y que abrirlos manda los datos a Anthropic.

Se miraron **3 de los 52**, no los 52: con tres alcanzaba para responder las dos preguntas que
bloqueaban F8, y minimizar la exposición de datos de terceros era lo proporcionado.

> **Decisión pendiente:** `CLAUDE.md` sigue diciendo que los datos reales nunca salen de la
> máquina. O se actualiza la regla, o se deja constancia de que esto fue una excepción puntual
> autorizada. **Hay que resolverlo**, porque hoy el documento y lo que se hizo no coinciden.

### 🔍 Lo que mostraron los 3 comprobantes — desarma varias suposiciones

| | 001 Macro | 003 BNA+ | 004 Santander |
|---|---|---|---|
| CBU receptor | ❌ solo `7192` | ✅ 22 dígitos | ✅ 22 dígitos |
| CUIT receptor | ✅ | ✅ | ❌ |
| ID COELSA | ✅ 22 chars | ❌ | ❌ |
| Nombre receptor | ✅ | ✅ | ✅ |
| Moneda | ARS | ARS | **USD** |

**1. Un error propio en el prompt v3.** En el Macro el `N° de operación` y el `ID COELSA` son
**el mismo valor** de 22 caracteres. v3 decía *"el número de operación del banco NO es el
COELSA"* — le enseñó a descartar el valor correcto. Por eso v3 bajó a 1/52 y v2 tenía 4/52.
Corregido en v4.

**2. No existe un campo identificador universal.** Ni el CBU ni el CUIT están en los tres. El
único presente siempre es el **nombre del titular**. Por lo tanto **`cbu_cvu_receptor` no
puede ser obligatorio**, como se había escrito más arriba en esta misma sesión: dejaría afuera
comprobantes perfectamente conciliables.

**3. Hay comprobantes en dólares.** El Santander es `U$S 100,00`. Si el extracto está en pesos,
ese comprobante **no debe cruzar** contra un movimiento de $100: sería un match falso por
coincidencia numérica. **El motor hoy no mira la moneda.** Es un agujero real.

**4. El CBU del BNA+ estaba completo y visible, y el modelo lo dejó vacío.** Ese sí es un fallo
de extracción y es lo que el fine-tuning puede arreglar.

### Propuesta abierta: cómo identificar la cuenta

La idea anterior —match por sufijo de CBU— **quedó en duda**: el Macro no muestra un CBU
parcial sino un número de cuenta (`CA $ 7192`), que no tiene por qué coincidir con los últimos
dígitos del CBU. No se puede asumir que sí.

Lo que se ve viable, en cascada de más a menos confiable:

```
1. CBU completo (22 dígitos)     cuando está          → seguro
2. CUIT del receptor             cuando está          → seguro, y el extracto lo tiene en 98,7%
3. Nombre del titular            siempre está         → el menos preciso, requiere normalizar
```

Para el paso 2 hace falta **agregar el CUIT de cada cuenta** a la tabla `cuenta`, que hoy solo
tiene `cbu` y `alias`. **Puede ser más fácil de conseguir que los CBU**, que están pendientes
desde la sesión 1.

**Toca `motor.ts`, cerrado con TDD y 32 tests.** No se hizo nada: requiere confirmación
explícita y tests primero.

### El COELSA es el gran problema abierto

En las tres versiones el modelo falla casi por completo: **1 a 4 de 52**. Es el campo de la
**regla 1 de la cascada**, la de mayor confianza, así que importa más que ningún otro.

**Pero falta un dato para saber de qué tipo de falla se trata**, y solo lo puede responder una
persona mirando los comprobantes: *¿estos comprobantes muestran un ID COELSA?* En el extracto
real solo lo trae el 3% de las filas. Si los comprobantes tampoco lo muestran, entonces `null`
es la respuesta **correcta**, el modelo está inventando cuando llena, y no hay nada que
entrenar. Si sí lo muestran, es el candidato número uno del fine-tuning de F9.

Sin esa respuesta no se puede decidir. **Preguntarlo antes de F8.**

### 🧨 F8 — los DOS bugs que mataron el intento anterior, encontrados

**Bug 1 · El formato del JSONL.** Verificado leyendo el código instalado, no la documentación
(`mlx_vlm/trainer/trainer.py`, clase `Dataset`):

```python
images = item["images"]          # plural
conversations = item["messages"]
```

`viejo/train.jsonl` trae `"image"`, `"prompt"` y `"answer"`. **Ninguna de esas tres claves
existe para el trainer.** Por eso nunca arrancó.

El formato correcto, **verificado empíricamente** pasando ejemplos por el `apply_chat_template`
real del processor de Qwen2-VL:

```json
{"images": ["ruta.jpg"],
 "messages": [{"role":"user","content":[{"type":"image"},{"type":"text","text":"..."}]},
              {"role":"assistant","content":[{"type":"text","text":"{...16 campos...}"}]}]}
```

| forma de `content` | ¿inserta el token de imagen? |
|---|---|
| lista de dicts con `{"type":"image"}` | **sí** ✅ |
| string plano | **no** ❌ |

**Con `content` como string el entrenamiento corre sin error y el modelo nunca ve una imagen.**
Horas de GPU para un resultado basura, sin ninguna señal de que algo anda mal. Es el peor tipo
de bug y por poco se repite.

> ## ⛔ ESTA PARTE ESTÁ MAL — corregida en la sesión 4
>
> Lo de arriba vale para el `apply_chat_template` **del processor de HF**, que es lo que se
> probó. Pero `lora.py` no usa ese: mete antes el suyo
> (`mlx_vlm.prompt_utils.apply_chat_template`), que **reconstruye los mensajes y pone el
> `{"type":"image"}` él solo**. Por el camino real del entrenamiento la conclusión se invierte:
> **`content` va como string plano.** La tabla correcta y la evidencia están en la sesión 4.
>
> El resto del bug 1 —que las claves son `images`/`messages` y no `image`/`prompt`/`answer`—
> sigue siendo cierto y sigue siendo lo que mató el intento anterior.

**Bug 2 · El ground truth del generador sintético está en el formato equivocado.** Medido sobre
las 10 plantillas de `viejo/generar_sinteticos.py`:

| Problema | Alcance |
|---|---|
| `monto` en formato argentino (`275.054,91`), y **2 de 10 ambiguos** (`198.005`) | 10/10 |
| `cuit` con guiones (`20-53594652-7`) | 10/10 |
| `coelsa_id` de 16 o 20 chars, o vacío — **ninguno mide 22** | 10/10 |

**Entrenar con esto habría empeorado el modelo respecto al zero-shot**, y el número de F10
habría salido negativo sin que se entendiera por qué.

**La solución no es tocar cómo se dibujan las imágenes.** Está bien que muestren `$ 275.054,91`,
porque así se ven los comprobantes reales. Lo que hay que normalizar es **la etiqueta**:

```
la imagen muestra:   $ 275.054,91     ← realista, se queda
la etiqueta dice:    275054.91        ← canónico, lo que debe aprender a producir
```

Así el modelo aprende justamente lo que se necesita: **traducir del formato visual al
normalizado**. Igual con el CUIT (`20-53594652-7` → `20535946527`).

**Se recomienda NO migrar de PIL a HTML**, contra lo que dice `PLAN.md` en F8: son 842 líneas
reescritas por una mejora estética, cuando el bug real era el formato del JSONL. Si se quiere
la migración, después de tener el entrenamiento andando.

> ⚠️ Al probar el generador se escribió un `.jpg` dentro de `viejo/comprobantes/`, que es de
> solo lectura. **Se borró y `viejo/` quedó como estaba.** El generador escribe en rutas
> relativas: hay que correrlo siempre con el cwd fuera de `viejo/`.

### Estado de F6 al cerrar la sesión

```
ia/salida_cruda.jsonl   v1 — intocable, primera medición
ia/salida_v2*.jsonl     v2 — crudo y rescatado
ia/salida_v3.jsonl      v3 — el baseline elegido
ia/validado.jsonl       v3 pasado por validar.py
ia/verdad_referencia.xlsx   la planilla para corregir a mano  ← acá sigue el trabajo
```

Con v3 validado: **6 de 52 comprobantes quedan completos** y 46 necesitan que una persona
complete algo. Sin contar el COELSA serían 14 completos y 38 con pendientes.

| Campo | Hay que cargarlo a mano en |
|---|---|
| `coelsa_id` | 29/52 |
| `cbu_cvu_emisor` | 22/52 |
| `cuit_emisor` | 13/52 |
| `cuit_receptor` | 12/52 |
| `cbu_cvu_receptor` | 10/52 |
| `fecha` | 8/52 |
| `hora` | 2/52 |

Ningún valor se corrigió ni se dedujo: lo que no pasó validación quedó en `null`.


