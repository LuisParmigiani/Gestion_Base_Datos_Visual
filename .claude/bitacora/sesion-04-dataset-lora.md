<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-07 · Sesión 4 — F8: el generador, y un cuarto bug

**Estado al empezar:** verificado, no supuesto. Postgres arriba, `pnpm test` 112 en verde, 2822
movimientos, 0 comprobantes, los 3 CBU en NULL, `verdad_referencia.xlsx` sin tocar desde que se
generó (F6 sin empezar), `ia/sinteticos/` vacío.

Se eligió **F8** entre las cinco opciones abiertas: es la única que no depende de datos que
tenga que pasar el usuario.

### Lo que se construyó

**`ia/generar.py`** — copia de `viejo/generar_sinteticos.py` (que quedó intacto: el `diff` da
157 líneas cambiadas y ningún archivo de `viejo/` fue modificado) con cinco cambios:

| Cambio | Por qué |
|---|---|
| `OUT_DIR` anclado a `__file__` | El original es relativo al cwd y ya escribió una vez dentro de `viejo/comprobantes/` |
| `gen_coelsa()` → 22 chars | El original daba 16 o 20. Alfabeto sin `I` ni `O`, que se confunden con 1 y 0 |
| `_gt()` emite la etiqueta **canónica** | `275054.91` y `20535946527`, mientras la imagen sigue mostrando `$ 275.054,91` y `20-53594652-7` |
| `verificar()` con 7 asserts | Corre en cada ejemplo generado. Es el chequeo que faltó la vez pasada |
| El volcado a JSONL, adentro | `viejo/gestionar_dataset.py` eran 60 líneas: no merecían archivo propio |

El `monto` se redondea con el **mismo** criterio con que el template lo dibuja: si la imagen
muestra `$ 198.005` sin centavos, la etiqueta dice `198005.00`. Etiquetar `198004.87` sería
enseñarle a inventar centavos que no están en la imagen. Dos de los diez templates dibujan sin
decimales y ese detalle los tocaba a los dos.

### 🧨 El cuarto bug — y por qué el chequeo obvio no lo agarra

**`lora.py` aplica `mlx_vlm.prompt_utils.apply_chat_template` por default**, y ese wrapper **no
respeta el `content` que le pasás**: lo reconstruye con `get_message_json`, que envuelve
`p["content"]` en `{"type":"text","text": …}` y agrega el `{"type":"image"}` por su cuenta.

Si le pasás la lista de dicts que documenta context7 —y que la sesión 3 dio por buena— queda
**anidada**, y la etiqueta que el modelo aprende a emitir termina siendo la repr de Python de
una lista:

```
malo:   ..."coelsa_id": null}'}]<|im_end|>      ← [{'type': 'text', 'text': '{…}'}]
bueno:  ..."coelsa_id": null}<|im_end|>
```

| forma de `content` (por el camino de `lora.py`) | token de imagen | etiqueta limpia |
|---|---|---|
| **string plano** | 1450 ✅ | **sí** ✅ |
| lista de dicts | 1450 ✅ | **no** ❌ |

**Lo peligroso es la primera columna: el token de imagen entra igual en las dos.** Mirar
`input_ids` —que es el chequeo que uno haría— no distingue. Solo se ve decodificando el texto.

La sesión 3 no midió mal: probó el `apply_chat_template` **del processor de HF**, donde la
lista sí hace falta. Lo que no vio es que `lora.py` mete su propio wrapper antes.

### Cómo se verificó — replicando el camino de `lora.py`, no la documentación

```
1. load_dataset  → 10 filas · columnas ['images', 'messages']
2. columnas images/messages presentes ✓
3. model_type=qwen2_vl · image_token_index=151655
4. apply_chat_template ✓
5. input_ids=(1, 1979) · pixel_values=(5800, 1176)
   token de imagen 151655 aparece 1450 veces
6. la etiqueta canónica llega LIMPIA al texto tokenizado ✓
7. control negativo (content = lista de dicts):
   token de imagen aparece 1450 veces — igual que el bueno, NO distingue
   ¿la etiqueta llega limpia? False
   → termina en '812137", "coelsa_id": null}\'}]<|im_end|>' ✓ el chequeo 6 lo agarra
```

**El control negativo es lo que le da valor al chequeo 6.** La primera versión del script
verificaba el token de imagen, daba verde, y no probaba nada: las dos formas dan 1450. El
script vive en el directorio temporal del job, no en el repo — es un chequeo de una sola vez,
no un test del proyecto.

### Las 6 mutaciones de `verificar()`, todas atrapadas

```
✓ monto en formato AR (275.054,91)      ← el bug de viejo/
✓ monto sin centavos (275054)
✓ CUIT con guiones (20-53594652-7)      ← el bug de viejo/
✓ coelsa de 20 chars                    ← el bug de viejo/
✓ CBU de 11 dígitos
✓ fecha en DD/MM/AAAA
```

Los 10 templates generan y validan: 10 bancos distintos, 3 con `coelsa_id` de 22 (MP, Macro,
Naranja X), 7 con `null` — que es lo correcto, no todos los bancos lo muestran.

### Decisiones de esta sesión

| Decisión | Motivo |
|---|---|
| **Se generaron 10 ejemplos, no 600** | Probar el pipeline antes de escalar. Generar 600 y recién ahí descubrir que el formato no carga es repetir el error anterior con más pasos en el medio |
| **El prompt de entrenamiento es `PROMPT_V3` importado de `extraer.py`** | No copiado. Entrenar con un prompt e inferir con otro invalidaría la comparación de F10 |
| **No se migró de PIL a HTML** | `PLAN.md` F8 lo pide, pero son 842 líneas por una mejora estética. Se posterga, como ya recomendaba la sesión 3 |
| **Sin lógica para excluir los 30 de F6** | El dataset es 100% sintético: ningún comprobante real puede entrar. La exclusión es automática por construcción |
| **Se corrigió el bloque de la sesión 3 en vez de reescribirlo** | La bitácora es un diario. Se dejó la conclusión vieja con una marca ⛔ que apunta acá |

### Las dos decisiones abiertas — resueltas por el usuario el 2026-08-07

**1. El dataset va 100% en pesos.** Se propuso agregar ~8% de comprobantes en USD y el usuario
decidió que no. **El riesgo queda anotado, no resuelto:** entre los 52 reales hay comprobantes
en dólares (el Santander 004 dice `U$S 100,00`), y un modelo entrenado sin un solo ejemplo en
USD puede aprender que `moneda` vale siempre `"ARS"` y devolver eso incluso viendo `U$S`. Eso
alimenta el agujero de diseño nº1 del motor: un match falso por coincidencia numérica.
**Si F10 muestra que `moneda` empeoró respecto al zero-shot, la causa es esta.**

**2. Se entrena con `PROMPT_V3` tal cual, con su error.** v3 dice *"el N° de operación del banco
NO es el COELSA"*, que la sesión 3 demostró falso para el Macro. Se deja porque mantiene la
comparación de F10 limpia —el mismo prompt en zero-shot y en fine-tuned—, y el error pasa a ser
material del informe en vez de una variable suelta. **Consecuencia esperada: el fine-tuning
refuerza el error y el `coelsa_id` sigue siendo el campo peor extraído.** No sorprenderse.

### Cómo se va a demostrar la mejora — el diseño de medición

Dos varas, y la primera no depende de nadie:

| Vara | N | Etiquetas | Qué prueba |
|---|---|---|---|
| **A · test sintético held-out** | ~120, semilla distinta, nunca entrenados | exactas por construcción, gratis | que el modelo aprendió la distribución sintética |
| **B · los 30 reales de F6** | 30 | corrección humana, ~50 min | **validez externa** — que sirve para el problema real |

La A sola alcanza para tener la tabla de F10. **La A + la B es lo que hace defendible el
trabajo**, porque permite escribir la diferencia entre las dos y llamarla por su nombre:
*domain gap*. Reportar solo la A sin aclarar qué mide sería inflar el número.

Material de informe que ya está medido y no hay que rehacer: los 4 prompts sobre los mismos 52
(591 / 637 / **664** / 528) como sección de baseline engineering, y el hecho de que **el COELSA
no se arregla con prompting** (1-4 de 52 en tres intentos) como justificación de por qué hace
falta entrenar.

### F9 · smoke test de 10 iteraciones — el pipeline corre

`ia/entrenar.py`, 10 pasos sobre los 10 ejemplos sintéticos. **Corrió de punta a punta y
guardó el adapter.** Tres números que salieron de ahí:

```
loss: 15.4 → 14.9 → 64.7 → 13.2 → 13.6 → 20.1 → 100.7 → 17.9 → 19.3 → 13.9
total 27.7 min · 166.5 s/paso
adapter: 154 MB
```

| Hallazgo | Qué significa |
|---|---|
| **166,5 s/paso** | 600 ejemplos × 1 epoch = **~28 horas**. No es viable así. La palanca es el tamaño de imagen: un comprobante son **1222 tokens de imagen** y eso domina el tiempo. Se agregó `--resize` a `entrenar.py` para poder medirlo |
| **Loss inestable, con picos de 65 y 100** | Lo esperable en un modelo de lenguaje es un dígito. Con batch 1 y 10 ejemplos no se puede concluir, pero **hay que mirarlo antes del run largo** |
| **La columna `segundos` del CSV mentía** | mlx evalúa perezoso: sin forzar `loss.item()` antes de parar el cronómetro se mide armar el grafo (0,2 s) y no el cómputo (166 s). Corregido |
| **`save_adapter` espera una ruta de ARCHIVO, no un directorio** | Error propio. Le pasaba el directorio y quedaba `ia/checkpoints/lora_bancos.safetensors` al lado de la carpeta, con el `adapter_config.json` un nivel más arriba. Corregido para dar `<salida>/adapters.safetensors`, que es lo que `PLAN.md` pide en F9 |

> Quedaron sueltos del smoke test, sin borrar: `ia/checkpoints/lora_bancos.safetensors` (154 MB)
> y `ia/checkpoints/adapter_config.json`. Se pueden borrar.

### ⚡ `--resize` baja el tiempo por paso 4,6 veces — medido

```
sin resize:            166,5 s/paso     600 pasos = ~28 horas   ← inviable
--resize 448 784:       35,8 s/paso     300 pasos = ~3,3 horas  ← viable
```

Lo que domina el tiempo son los **tokens de imagen**, no los parámetros. LoRA entrena
40,37 M de 7615 M (**0,53%**).

**Bug de mlx-vlm 0.1.15 que hay que esquivar para poder usar `--resize`:** `lora.py` indexa el
dataset con **slice** (`datos[i:i+batch]`), y ahí `prepare_inputs` recibe `images` anidado
(`[[ruta]]` en vez de `[ruta]`). Sin resize no molesta; con resize revienta en `resize_image`
con `AttributeError: 'list' object has no attribute 'width'`. **Con batch 1 se indexa con
entero** y funciona. `ia/entrenar.py` ya lo hace.

> ⚠️ **Riesgo anotado, no resuelto:** se entrena con imágenes redimensionadas a 448×784 pero
> `extraer.py` infiere a tamaño completo. Es un desajuste train/inferencia que puede costar
> precisión. Si F10 sale peor de lo esperado, **esto es lo primero que hay que mirar.** El
> arreglo es redimensionar también en inferencia.

### Corrida `lora_v1` — lanzada el 2026-08-07

```
dataset:  ia/sinteticos/train.jsonl · 300 ejemplos sintéticos (semilla 2026)
config:   1 epoch · 300 pasos · batch 1 · lr 2e-5 · rank 16 · alpha 32 · dropout 0.05
salida:   ia/checkpoints/lora_v1/adapters.safetensors + curva_loss.csv
log:      ia/checkpoints/entrenamiento_lora_v1.log
duración estimada: ~3,3 horas
```

**Al terminar**, para que entre en la comparación:

```bash
ia/.venv/bin/python ia/extraer.py --adaptador ia/checkpoints/lora_v1 \
    ia/comprobantes/*.jpeg > ia/salida_lora_v1.jsonl     # falta el flag --adaptador
cd web && pnpm importar:comprobantes ../ia/salida_lora_v1.jsonl lora_v1 \
    --prompt v3 --adaptador ia/checkpoints/lora_v1 --respecto-de v3 \
    --imagenes ../ia/comprobantes \
    --desc "Primer fine-tuning LoRA sobre 300 sintéticos." \
    --cambio "Se pasó de zero-shot a LoRA rank 16 sobre 300 comprobantes sintéticos..."
```

> **`extraer.py` todavía NO tiene el flag `--adaptador`.** Hay que agregarlo antes de poder
> medir el modelo entrenado.

---

### ⛔ Las 4 trampas de `mlx-vlm 0.1.15` que hay que esquivar

`ia/entrenar.py` ya las esquiva todas. Se anotan porque **la documentación no las dice** y
cualquiera que toque el entrenamiento las vuelve a pisar.

**1. `python -m mlx_vlm.lora` NO sirve tal cual.** `lora.py` hace `load()` y nunca parchea el
image processor "fast", así que revienta con `ValueError: Only returning PyTorch tensors is
currently supported` — el mismo error que `extraer.py` ya tenía parcheado. Por eso existe
`ia/entrenar.py`: replica el `main()` de `lora.py` agregando dos líneas.

```python
from transformers import Qwen2VLImageProcessor
processor.image_processor = Qwen2VLImageProcessor.from_pretrained(MODELO, use_fast=False)
```

**2. `--apply-chat-template` está declarado al revés.** En 0.1.15 es `action="store_false"`:
el default ya es aplicarlo y **pasar el flag lo desactiva**. No pasarlo.

**3. `lora.py` indexa el dataset con slice** (`datos[i:i+batch]`), y ahí `prepare_inputs`
recibe `images` anidado (`[[ruta]]` en vez de `[ruta]`). Sin `--resize` no molesta; con
`--resize` revienta en `resize_image` con `AttributeError: 'list' object has no attribute
'width'`. **Con batch 1 se indexa con entero** y funciona.

**4. El `content` de los mensajes va como string plano**, no como lista de dicts — ver el
bloque del cuarto bug más arriba. Es el único de los cuatro que no da error: entrena igual y
el modelo aprende a emitir basura.

### Cómo se prueba el circuito a mano

```
1. /extracto      → subir TRANSFERENCIAS.xlsx, mirar el resumen por cuenta
2. /comprobante   → imagen + los 16 campos (monto y fecha son obligatorios)
3. /              → aparece en el tablero con su estado
4. /resolver      → si quedó ambiguo, elegir el candidato
```

---
