# Sesión 9 — Por qué colapsaron los dos LoRA: `alpha` significaba otra cosa

**2026-08-09.** `lora_v2` terminó sus 333 pasos y **devolvió un chorro de comillas en los 16
apartados**: cero campos extraídos, el mismo síntoma que `lora_v1`. Esta sesión encuentra la
causa real —que no era la que estaba asentada— y arregla el proceso que dejó que dos corridas
de 7 y 9 horas terminaran sin que nadie se enterara hasta el final.

---

## La causa raíz

`mlx_vlm/trainer/utils.py`, `LoRaLayer.__call__`:

```python
return y + (self.alpha * lora_update)
```

**`alpha` es la escala DIRECTA del update. No se divide por `rank`.** El default del CLI
oficial de mlx-vlm es **`0.1`**.

`ia/entrenar.py` tenía `--alpha` con default **32**, escrito con la convención de
HuggingFace/PEFT, donde la escala efectiva es `alpha/rank` (32/16 = **2**). En mlx-vlm eso no
da 2: da **32**, o sea **320× el default de la librería**.

### El experimento que lo prueba

El **mismo adapter entrenado**, la **misma imagen**, cambiando **solo `alpha`** en el
`adapter_config.json` que lee `apply_lora_layers`:

| alpha | Salida |
|---|---|
| **0** | ✅ JSON válido — `monto=12000.00 · fecha=2026-03-26 · cuit=20-46217018-2` |
| **0,1** | ✅ JSON válido, idéntico |
| **2** | ❌ `.AF:mm.AF:mm.AF:mm...` |
| **32** | ❌ `" " " " " " "...` |

Una sola variable, efecto monótono. `alpha=0` reproduce el modelo base, lo que además valida
que toda la cañería de inferencia está sana.

### Por qué la loss no lo detectó nunca

Es lo más importante de esta sesión. **El entrenamiento minimizó la loss correctamente** — y
encontró una solución degenerada: emitir el mismo token para siempre. Una salida de entropía
casi nula tiene loss baja. Las curvas de v1 y v2 bajaban de verdad y convergían de verdad,
hacia un modelo inservible.

Los pesos lo confirman: al terminar, **`B` quedó en rms 0,003 y `A` no se movió del init**. Con
escala 32, un `B` minúsculo ya arrasaba la representación. El modelo no necesitaba aprender casi
nada para colapsar.

> **La lección, más general:** una métrica de entrenamiento no puede validar una capacidad que
> no mide. La loss mide predicción del próximo token; que el modelo siga produciendo JSON es
> otra cosa. Hay que medir lo segundo, explícitamente.

---

## ⛔ Dos correcciones al registro

### 1. `bitacora/sesion-06-lora-v2.md`: `--resize` NO era la causa

Ese archivo concluye que `lora_v1` se rompió por `--resize 448 784` ("no rompía la cañería:
rompía la legibilidad"), y `BITACORA.md` lo elevó a **"causa raíz medida"** con la orden de no
volver a usar `--resize`.

**Era falso, y la evidencia para descartarlo estaba en la misma página.** La tabla de tres
pruebas de la sesión 6 dice, en su fila 2:

| adapter **sin** resize | la misma basura → **el adapter está roto en sí mismo** |

Esa fila ya decía que el problema era independiente del resize. El párrafo siguiente concluyó
lo contrario. **La conclusión contradecía su propia evidencia**, y nadie lo notó durante dos
sesiones.

`lora_v2` se entrenó **sin `--resize`** y colapsó igual. Los dos `adapter_config.json`
comparten `alpha: 32`.

**Qué queda en pie de la sesión 6:** la curva calidad-vs-tamaño (menos píxeles ⇒ menos
legible) sigue siendo una medición válida y `--resize` sigue siendo desaconsejable por eso.
Lo que cae es que fuera **la causa del colapso**.

### 2. `bitacora/sesion-08-checkpoints.md`: dos afirmaciones equivocadas

- **"SIGHUP, se cerró la terminal"** — falso. La segunda corrida se lanzó con
  `nohup` + `disown` + `< /dev/null`, o sea inmune a SIGHUP, y **murió en el paso 162, el
  mismo**. La causa real: el ejemplo del índice 162 (`ia/comprobantes/033.jpeg`, 2,47 MPx,
  ~3078 tokens de imagen) mata el proceso. Reproducido en aislamiento: ese ejemplo solo,
  paso 1, muere. Se sacaron del dataset los índices 162 y 278 (los dos únicos por encima de
  1938 tokens) → `ia/sinteticos/train_v2_sin_gigantes.jsonl`, 333 ejemplos.
  El pico de RSS fue 4,6 GB de 24, así que **no es falta de RAM del sistema**; queda como
  hipótesis abierta del lado de Metal/GPU. No hizo falta cerrarla para arreglarlo.
- **"El estado del optimizador no se guarda; el costo es un transitorio de unos pasos"** —
  falso y caro. Reanudar con Adam en cero **destruyó 5 h de entrenamiento**: la loss se fue de
  7,9 a 31 en 25 pasos, subiendo de forma monótona, y como cada paso pisa el checkpoint, los
  pesos buenos se perdieron. Ya está arreglado (se guarda `optimizador.safetensors` y hay
  checkpoint de mejor loss), pero **la decisión original estaba mal tomada**, y la señal
  —el mismo salto visible en el smoke test— se explicó como ruido en vez de investigarse.

---

## Los arreglos

| Qué | Dónde | Por qué |
|---|---|---|
| `--alpha` default `32` → **`0.1`** | `entrenar.py` | La convención de mlx-vlm, documentada en el `--help` para que no se repita |
| **Canario de generación** | `entrenar.py` | Cada N pasos genera de verdad y verifica que salga JSON. Aborta tras K fallos seguidos |
| `#trainable params` a stderr | `extraer.py` | Iba a **stdout**, o sea al JSONL: contaminó `salida_lora_v2.jsonl` y el importador descartó el archivo entero |
| `parsear()` acepta no-objetos | `extraer.py` | `json.loads('5')` da un `int` y `datos.get()` reventaba **la corrida entera de 51**. `rescatar()` ya se protegía; este camino no |

### El canario, en detalle

Es el arreglo del **proceso**, no del parámetro. Usa el mismo prompt (`PROMPTS["v3"]`) y el
mismo `parsear()` que la extracción real, importados de `extraer.py`: si usara los suyos podría
dar verde mientras la extracción recibe basura. La imagen tiene que estar **fuera** del dataset
o mide memorización.

**Falla cerrado.** Una versión anterior devolvía "no evaluable" ante una excepción, y en el
Test B un modelo tan roto que su salida no decodificaba en UTF-8 quedó anotado como *"el
chequeo falló"* en vez de *"el modelo falló"* — subestimando el colapso justo en el caso más
grave. Ahora la imagen se valida al arrancar y después **cualquier excepción cuenta como
fallo**.

**Costo medido: ~60-110 s por canario**, no los ~25 s estimados (paso 2: 127,5 s contra 16,5 s
del paso 3). Con `--canario 25` sobre pasos de ~100 s son **+3,6%**. A cambio detecta en ~40
min lo que costó 7 h y 9 h.

### Verificación

- **Test A** (`--alpha 0.1`): canario sano en los pasos 2 y 4. Sin falsos positivos.
- **Test B** (`--alpha 100`, tolerancia 2): **abortó en el paso 4** con mensaje accionable.
  La alarma suena de verdad — un canario sin probar es peor que no tenerlo.
- **`parsear()`**: 11 casos, incluidos los 5 que reventaban (`5`, `"texto"`, `[1,2]`, `null`,
  `true`). Todos degradan a `sin_parsear` en vez de excepción.

---

## La vara para medir, ya calculada

Aciertos del modelo **base** restringidos a los **mismos 16 apartados**, con el mismo
`normalizarCampo` que usa `/corridas` (no una normalización paralela en SQL):

| corrida | sobre los 51 revisados | **sobre los 16 apartados** |
|---|---|---|
| **v1** | 532/816 (65%) | **177/256 (69%)** ← la vara honesta |
| v2 | 349/816 (43%) | 108/256 (42%) |
| v3 | 578/816 (71%) | 193/256 (75%) — inflado, `corrida_base` es v3 |
| v4 | 338/816 (41%) | 105/256 (41%) |

**Los 16 apartados son algo más fáciles que el conjunto de 51** (69% contra 65% en v1).
Comparar el LoRA contra el 65% le habría regalado 4 puntos.

---

## El segundo bug: una tilde puede matar la corrida entera

Apareció calibrando, y es **de la librería**, no del proyecto.

`mlx_vlm/tokenizer_utils.py:189`, `BPEStreamingDetokenizer.add_token`: acumula tokens en
`_unflushed` y **descarga recién cuando llega uno que empieza con espacio**. Si ese corte cae
en medio de un carácter multibyte —**cualquier tilde, ñ o ¡ del español**— hace
`.decode("utf-8")` sin tolerancia, tira `UnicodeDecodeError` y **se propaga hasta matar la
generación completa**. Visto en vivo: byte `0xa1`, el segundo de `"¡"`.

No se pierde una imagen: se pierde la corrida de 51. Las 4 corridas v1-v4 (204 extracciones)
nunca lo dispararon, así que es raro — pero en un proyecto de comprobantes en español es una
mina puesta.

**Arreglo:** `parchear_detokenizador()` en `extraer.py`, que reemplaza `add_token` y
`finalize` por copias idénticas salvo `errors="replace"`. Lo llaman la extracción **y** el
canario de `entrenar.py`. Un carácter partido queda como `U+FFFD` y ese campo falla la
validación, que es el resultado honesto.

### ⛔ Y una corrección a lo que dice más arriba en este mismo archivo

Arriba se afirma que el canario "falla cerrado" y que eso es lo correcto. **Las dos versiones
del canario estaban mal, en direcciones opuestas:**

- **Fallar abierto** (la primera): un modelo tan roto que su salida no decodificaba quedaba
  anotado como *"el chequeo falló"*. Subestimaba el colapso.
- **Fallar cerrado** (la segunda): el bug del detokenizador se anotaba como colapso del
  modelo. **Habría abortado una corrida SANA.** Pasó de verdad: el canario marcó ✗ en el paso
  10 de la calibración, y ese mismo checkpoint, con el parche puesto, devuelve JSON perfecto
  (`monto 12000 · fecha 2026-03-26 · nombre_emisor MercadoPago`).

La solución no era elegir entre abierto y cerrado: era **quitar la ambigüedad** arreglando el
crash de la librería. Recién ahora "excepción ⇒ modelo roto" es una inferencia válida.

> **La lección:** una alarma que puede dispararse por dos causas distintas no sirve para
> decidir. Antes de ajustar su sensibilidad, hay que eliminar la causa espuria.

## Tres errores de operación que costaron tiempo, para no repetirlos

1. **Lanzar sin `caffeinate` y a batería.** La primera calibración hizo **9 pasos en 12 horas**
   porque la Mac durmió toda la noche. La advertencia estaba escrita en la bitácora desde la
   sesión 8 y se ignoró al lanzar. **Verificar `pmset -g batt | grep "AC Power"` ANTES de
   lanzar**, no después.
2. **`pgrep -f entrenar.py` miente.** Matchea también el `bash -c` y el `caffeinate` que
   envuelven al proceso, porque la cadena está en su línea de comando. Un "sigue corriendo"
   puede ser el wrapper con el python muerto. Lo correcto:
   `ps -eo command | grep -cE '[p]ython.*entrenar\.py'`.
3. **Encadenar esperadores en background.** Se lanzaron tres bucles `until` esperando el mismo
   evento; no hacían daño pero ensuciaban y confundían. Uno alcanza.

## Lo que queda abierto

- **Calibrar `alpha`**: corridas cortas de 40 pasos con el canario puesto, comparando `0.1`
  contra `1.0`, antes de comprometer una corrida larga. Hay que mirar **dos** cosas: que el
  canario siga verde **y** que la loss baje de verdad — con alpha muy chico el otro modo de
  falla es no aprender nada y terminar empatando con el modelo base.
- Por qué el ejemplo de ~3078 tokens de imagen mata el proceso sin dejar registro.
- `ia/salida_lora_v2.jsonl` y `_limpio.jsonl` quedan como evidencia del colapso y del bug de
  stdout.
