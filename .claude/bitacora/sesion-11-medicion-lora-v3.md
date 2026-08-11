# Sesión 11 — `lora_v3` terminó, y por fin hay un número medido

**2026-08-10, tarde y noche.** Continuación directa de la sesión 10.

---

## 1. La corrida murió por un reinicio, no por un bug

Al abrir la sesión, `lora_v3` no estaba corriendo. Había muerto en el **paso 113 de 333**,
con el log terminando limpio, sin traceback y sin `.panic`.

```
last reboot     Mon Aug 10 14:37        uptime: up 5 mins
último checkpoint guardado: 14:35:34 (paso 112)
```

**La Mac se reinició a las 14:37.** Es el único asesino que la bitácora ya tenía anotado
("lo que sí lo mata: apagar, reiniciar o suspender") y esta vez se cumplió al pie de la letra.
No fue un gigante del dataset, ni memoria, ni `SIGHUP`.

El checkpoint por paso hizo exactamente lo que se diseñó: los tres archivos coincidían en el
paso 112 (pesos, optimizador y estado), `--continuar` lo aceptó y se perdieron **dos minutos
de cómputo**. Comparar con las 7 h y 9 h que costaron las muertes de agosto.

> **Cómo verificar un checkpoint antes de reanudar** — vale la pena porque falla barato:
> ```python
> mx.load(d+"adapters.safetensors", return_metadata=True)[1].get("paso")
> mx.load(d+"optimizador.safetensors", return_metadata=True)[1].get("paso")
> # los dos tienen que coincidir con estado.json["paso"]
> ```

### La reanudación y el ritmo

```bash
nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py \
  --dataset ia/sinteticos/train_v2_sin_gigantes.jsonl \
  --lr 1e-4 --alpha 0.1 --canario 25 \
  --salida ia/checkpoints/lora_v3 --continuar \
  >> ia/checkpoints/lora_v3.log 2>&1 < /dev/null & disown
```

**El log va en append (`>>`), no en `>`.** Con `>` se habrían borrado los 113 pasos ya
registrados, que son material del informe.

Cerró con `total 344.2 min · 93.9 s/paso · 220 pasos` y `curva_loss.csv` en 334 líneas, que
es el criterio de listo.

> ⚠️ **El canario cuenta los pasos DE LA CORRIDA EN CURSO, no los absolutos.** Al reanudar
> desde el 114, los 🐤 caen en 138, 163, 188… y no en 125, 150, 175. Lo mismo con la ventana
> de 20 losses del "mejor": vuelve a estar activa recién 20 pasos después de reanudar. Mirar
> el log esperando un canario en un múltiplo de 25 absoluto hace perder media hora.

---

## 2. La corrida fue sana: 12 canarios, 0 fallidos

**Es la primera corrida larga del proyecto que termina entera y produciendo JSON.** `v1` y
`v2` terminaron colapsadas devolviendo comillas. Sobre los 16 apartados, `lora_v3` parsea
**16/16** con 88-91% de los campos con contenido.

El colapso, como causa de fracaso, **está cerrado**. `alpha 0.1` lo resolvió.

---

## 3. La medición — cómo se hizo

Dos extracciones sobre los 16 apartados, con **prompt v3 y sin `--resize`**, que es la misma
configuración con que se entrenó (`resize: null` en `estado.json`) y con la que corre el
canario. Medir con otra combinación mide otra cosa.

```bash
ia/.venv/bin/python ia/extraer.py --adaptador ia/checkpoints/lora_v3/mejor  <16 jpeg> > ...
ia/.venv/bin/python ia/extraer.py --adaptador ia/checkpoints/lora_v3        <16 jpeg> > ...
cd web && node --env-file=.env.local src/lib/importar-comprobantes.ts \
  ../ia/salida_lora_v3_mejor.jsonl lora_v3_mejor --prompt v3 --adaptador ... \
  --respecto-de v3 --cambio "..." --imagenes ../ia/comprobantes
```

Las dos cargaron **16 extracciones y 0 comprobantes nuevos**, que es la señal de que se
aparearon con los que ya estaban en vez de duplicarlos.

> 💡 **En zsh, `$VAR` con una lista de rutas NO se separa en palabras** como en bash: se pasa
> como un único argumento y `ls` responde "No such file or directory" con los 16 nombres
> pegados. Usar expansión de llaves `{002,003,...}.jpeg` o un array `IMGS=(...)`.

### `web/comparar-lora.ts` — por qué existe

`/corridas` mide cada corrida sobre los comprobantes que **esa** corrida tiene: `v1` tiene 51
y las del LoRA 16. Sus porcentajes no se pueden poner uno al lado del otro. El script
restringe a la intersección y **reusa `normalizarCampo` del importador** en vez de comparar
por su cuenta — una comparación paralela daría un número que no coincide con la pantalla y no
se sabría cuál creer.

---

## 4. El resultado

**Sobre los 16 apartados, 256 campos por corrida:**

| Corte | v1 (base) | `lora_v3_mejor` | `lora_v3_final` |
|---|---|---|---|
| **Global** | **69,1%** (177) | 53,9% (138) | 59,4% (152) |
| Sin `tipo_operacion` | 67,5% | 57,5% | 63,3% |
| **Sin Mercado Pago** | 50,9% (57/112) | 55,4% | **58,0%** (65/112) |
| Solo Mercado Pago | **83,3%** (120/144) | 52,8% | 60,4% |
| **Los 6 de la conciliación** | 74,0% (71/96) | 72,9% | **80,2%** (77/96) |

Los 6 de la conciliación: `monto`, `fecha`, `moneda`, `cuit_emisor`, `cbu_cvu_receptor`,
`referencia`.

**En una línea: el modelo base es un especialista en Mercado Pago y mediocre en todo lo demás;
el LoRA es parejo.** El entrenamiento aplanó al modelo — le sacó la especialización y le subió
el piso.

### Por campo

**Mejoró justo donde el base inventaba** (el modo de falla dominante de F7 era
`cbu_cvu_emisor` inventado en 24 de 51):

| Campo | v1 | `lora_v3_final` |
|---|---|---|
| `cbu_cvu_emisor` | 7/16 | **13/16** |
| `cbu_cvu_receptor` | 10/16 | **14/16** |
| `referencia` | 7/16 | **12/16** |

**Empeoró en texto:** `nombre_receptor` 9→**2**, `cuit_receptor` 11→8, `cuit_emisor` 12→9,
`hora` 15→11. El patrón es coherente: mejor en cadenas numéricas largas, peor en texto libre.
El `nombre_receptor` 9→2 es la caída más fea y queda sin explicar.

### Por entidad emisora (la de la verdad corregida)

| Entidad | n | v1 | `lora_v3_final` |
|---|---|---|---|
| Mercado Pago | 9 | **83%** | 60% |
| Galicia | 2 | 69% | 59% |
| Macro | 1 | 38% | **75%** |
| Nación | 1 | 44% | **63%** |
| Naranja X | 1 | 69% | 56% |
| sin dato | 2 | 34% | **47%** |

**Los 16 apartados son 56% Mercado Pago.** El 69% global es, en buena medida, "qué tan bien
lee Mercado Pago". Fuera de esa entidad son **7 comprobantes / 112 campos**: el 58% contra
50,9% es una señal, no una conclusión.

---

## 5. Tres descuentos que hay que hacerle al número

### ⛔ `tipo_operacion` cuenta 0/16 y NO es un error de lectura

| | |
|---|---|
| La verdad dice | `Transferencia` |
| El LoRA dice | `transferencia_saliente` — **16 de 16** |

Es el vocabulario del generador sintético contra el de la verdad. **Acertó los 16 y cuenta
cero: 6,3 puntos.** Es un bug del dataset que va a envenenar toda medición futura hasta que se
alinee en `generar.py`. Se detecta comparando los valores distintos de un campo categórico
entre `comprobante` y `extraccion.campos`, y **conviene hacerlo con cada campo de vocabulario
cerrado antes de creerle a un porcentaje**.

### ⛔ El "mejor" checkpoint era el PEOR

`media_20` eligió el paso 218 (**53,9%**) sobre el final, paso 333 (**59,4%**). **La loss
ordenó los checkpoints al revés.** Tercera vez en el proyecto que una métrica de entrenamiento
no sigue a la capacidad: después del colapso de `v1`/`v2` y de la calibración que no pudo
elegir `alpha`. **`mejor/` sirve como red de seguridad contra la divergencia, no como
selector de calidad.**

### ⚠️ La vara y el LoRA usan prompts distintos

`v1` se midió con prompt v1 y el LoRA con v3. Es cada uno en su mejor configuración, que es lo
justo, pero es una variable mezclada y no se puede omitir al reportar.

---

## 6. Dos hallazgos en el código de `mlx-vlm` que explican el techo

Los dos salieron de leer la librería, no de suponer. Son la respuesta a "¿se puede aplicar el
LoRA de forma más eficiente?".

### 🔴 La loss se calcula sobre TODA la secuencia, no sobre la respuesta

`trainer.py:195` — `Trainer.__init__` tiene **`train_on_completions=False`** por default, y
`entrenar.py:224` no lo pasa:

```python
if self.train_on_completions:
    ...  # enmascara todo hasta el token `assistant`
else:
    weight_mask = None          # ← la loss cubre prompt + tokens de imagen + respuesta
```

O sea que **el entrenamiento gastó una fracción grande del gradiente en aprender a predecir su
propio prompt** y las posiciones de imagen. Explica de una la loss estancada en ~5,0 por token
(perplejidad ~150) y por qué 333 pasos movieron casi lo mismo que 40.

✅ **Verificado que `assistant_id=77091` es correcto para Qwen2-VL:**
`tok.decode([77091]) == 'assistant'`. El default de la librería sirve para este modelo.

⚠️ Sin verificar: `np.where(input_ids == assistant_id)[1]` asume **una sola aparición** del
token por secuencia. Si la palabra apareciera también en el prompt, el `reshape(-1, 1)`
rompería. Los prompts del proyecto están en español, así que probablemente no, pero **va con
un smoke test de 10 pasos antes de una corrida larga.**

### 🔴 El LoRA NUNCA toca la parte visual — está clavado en la librería

`trainer/utils.py:41` — `get_peft_model` recorre **solo** `model.language_model.named_modules()`,
y `find_all_linear_names` además saltea a propósito `vision_tower`, `mm_projector`,
`vision_resampler` y `aligner`.

**El encoder visual está congelado.** Lo que se entrena es "cómo escribir la respuesta dado lo
que la parte visual ya vio", no "cómo ver mejor". No es una decisión del proyecto: es el techo
de mlx-vlm 0.1.15.

Explica el patrón de la medición: mejora en disciplina de salida y en copiar cadenas
numéricas largas, no mejora en leer texto que el encoder resolvió mal.

---

## 7. Lo que quedó decidido y lo que quedó abierto

**Decidido:**
- El camino del LoRA **no está muerto**: gana fuera de Mercado Pago y gana en los 6 campos que
  deciden la conciliación. Va en la dirección que el proyecto necesita.
- La medición se reporta **desagregada por entidad**, nunca como un promedio global: con 56%
  de Mercado Pago, el global mide sobre todo una entidad.

**Abierto, en orden de retorno esperado:**
1. `train_on_completions=True` — un argumento, y es el candidato más fuerte para el techo.
2. Alinear el vocabulario de `tipo_operacion` en `generar.py`. Devuelve 6 puntos de medición.
3. `alpha 1.0`, que quedó calibrado y sin usar. Este LoRA aprendió con un décimo de escala.
4. Que el checkpoint lo elija la medición sobre los apartados, no `media_20`.
5. Por qué se rompió `nombre_receptor` (9→2).
6. Más comprobantes reales y más variedad de sintéticos — el usuario los consigue el 11-ago.
7. Apartar **entidades enteras** del entrenamiento (leave-one-bank-out) en vez de comprobantes
   sueltos: es la única medición que contesta "¿anda con un banco que nunca vio?".

**Archivos nuevos:** `ia/salida_lora_v3_mejor.jsonl`, `ia/salida_lora_v3_final.jsonl`,
`web/comparar-lora.ts`. Corridas nuevas en la base: `lora_v3_mejor`, `lora_v3_final`.

---

## 8. Lo que se aplicó la misma noche (2026-08-10, 21:30-22:00)

### `generar.py` — vocabulario alineado a la verdad

`transferencia_saliente` → **`Transferencia`**. El dataset se contradecía consigo mismo:

| Origen | Etiqueta que traía |
|---|---|
| 300 sintéticas | `transferencia_saliente` |
| 32 reales | `Transferencia` |
| 1 real | `Transferencia enviada` |

El modelo aprendió la mayoritaria, que era la equivocada. **No se tocaron las claves
`(banco, "transferencia_saliente")` de la tabla de plantillas**: enrutan qué función dibuja el
comprobante y no salen en la etiqueta. Está comentado en el código para que nadie las "arregle".

### `ia/sinteticos/train_v3.jsonl` — el dataset ya generado, parcheado

333 líneas. Se cambiaron **solo las 300 sintéticas**; las reales no se pisan porque lo que
dicen es la corrección de una persona (incluida la única que dice `Transferencia enviada`).
Regenerar habría implicado volver a dibujar 630 imágenes sin necesidad. Verificado que no se
coló nada más:

```
imágenes distintas: 0 · prompts distintos: 0
claves cuyo valor cambió: {'tipo_operacion'}
```

`train_v2_sin_gigantes.jsonl` queda intacto como evidencia.

### `entrenar.py` — `train_on_completions=True`

La quinta corrección a mlx-vlm. **Verificado ANTES de activarlo**, porque el enmascarado hace
`np.where(input_ids == 77091)[1]` con un `reshape(-1, 1)` que asume una aparición por
secuencia:

```
apariciones del token 'assistant' por ejemplo: {1: 333}
ejemplos con != 1 aparición: NINGUNO ✅
```

El `assistant.` del system prompt de Qwen2 (*"You are a helpful assistant."*) **no cuenta**:
lleva espacio delante y tokeniza distinto de 77091. Sin esta verificación el riesgo era
romper en la primera corrida larga.

### Smoke test: 10 pasos, aprobado

```
epoch 0 · paso  5/10 · loss 0.0615 · 11.2s · ✓ · 🐤
epoch 0 · paso 10/10 · loss 0.0440 · 29.0s · ✓ · 🐤
total 11.6 min · 69.8 s/paso · 10 pasos
```

Los dos canarios verdes: el nuevo enmascarado **no rompe la generación**.

> ⚠️ **La loss de 0,03-0,06 NO es comparable con los 5,0 de `lora_v3`.** No es que el modelo
> mejoró 100×: ahora la CE se suma solo sobre los tokens de la respuesta pero se sigue
> dividiendo por `ntoks` = **toda** la secuencia (`trainer.py:258`), así que el número también
> está diluido ~3,7×. Es otra medición, no la misma más baja. **Ninguna curva anterior se
> puede poner en el mismo gráfico que las de acá en adelante.**

> 💡 Con la loss dos órdenes de magnitud más chica, **el gradiente también lo es**: es
> probable que `lr 1e-4` quede corto. Se decide mirando la curva de una corrida real, no
> adivinando, y **es una segunda variable** — no mezclarla con `alpha` en la misma corrida.

**Verificado en vivo:** `/probar` anda contra el modelo real, sin base levantada y sin guardar
nada — el usuario la probó y la aprobó.
