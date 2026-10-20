# La inteligencia artificial

> Para saber más. Cómo se entrenó el modelo que lee los comprobantes, de dónde salieron los datos de entrenamiento, cada corrida y cómo se midió. La versión corta está en el [README](../README.md).

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

