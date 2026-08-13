# Sesión 15 — `lora_v4` medido, y los cuatro sesgos que tenía el generador

**2026-08-11 al 13.** Se entrenó `lora_v4`, se lo midió, y al mirar por qué fallaba sobre un
comprobante del usuario se encontró que el generador sintético le había enseñado cuatro cosas
falsas. Se corrigieron las cuatro contra datos medidos, y quedó corriendo `lora_v4_v2`.

---

## 1. `lora_v4`: 842 pasos, 21 h, la corrida más limpia hasta acá

```
--dataset train_v4.jsonl --lr 1e-4 --alpha 0.1 --canario 25 --salida ia/checkpoints/lora_v4
```

**842/842 pasos · 33 canarios verdes · 0 fallidos · 1259,5 min (89,7 s/paso).** Segunda corrida
larga seguida que termina entera. El colapso, como modo de falla, está cerrado.

### El ritmo real: 89,7 s/paso, no 24

⛔ **La columna `segundos` de `curva_loss.csv` NO mide lo que tarda un paso.** `entrenar.py`
arranca el cronómetro antes de `train_step` y lo para en `loss.item()` (líneas 370-382): el
`guardar()` de los 484 MB (161 de adapters + 323 del optimizador) y el canario quedan **fuera**.

| | |
|---|---|
| Cronómetro interno (`dt`) | 24,3 s/paso |
| Reloj de pared | **81-90 s/paso** |
| Diferencia no cronometrada | ~57 s/paso |

**Para estimar una corrida se usa `ps -o etime`, nunca la curva.** La nota vieja de la bitácora
—*"`--cada 1` está medido que no alarga el entrenamiento"*— salía de esa métrica ciega, que por
construcción no puede ver el costo de guardar.

⚠️ **Pero el overhead NO siempre es el checkpoint.** En `lora_v4_v2`, con `--cada 5`, el reloj
siguió en ~110 s/paso **con el cómputo mismo en 83-152 s**. Ahí el cuello era la memoria (ver §6),
no el guardado. Las dos causas existen y se distinguen mirando `dt`: si `dt` sube, es memoria;
si `dt` está bajo y el reloj alto, es el guardado.

---

## 2. La medición: `lora_v4` gana en todos los cortes

`extraer.py --adaptador ia/checkpoints/lora_v4 --prompt v3` sobre los 16 apartados → importado
como corrida `lora_v4_final` → `comparar-lora.ts`.

**El prompt se verificó, no se supuso:** el del dataset mide 825 caracteres y coincide **exacto**
con `PROMPTS["v3"]`. Inferir con otro habría castigado al LoRA sin que se notara.

| Corte | base v1 | `lora_v3_final` | `lora_v4_final` |
|---|---|---|---|
| Global | 69,5% | 69,9% | 84,0% |
| Sin `tipo_operacion` | 67,9% | 74,6% | 82,9% |
| **Sin `tipo_operacion` NI `moneda`** ← el honesto | **66,1%** | **72,8%** | **81,7%** |
| Sin Mercado Pago | 53,6% | 67,9% | 80,4% |
| Solo Mercado Pago | 81,9% | 71,5% | **86,8%** |
| Los 6 de la conciliación | 76,0% | 87,5% | 91,7% |

### ⛔ El 84% está inflado: `tipo_operacion` y `moneda` son constantes

En los 800 sintéticos, `tipo_operacion` tiene **un solo valor** ("Transferencia", 800 veces) y
`moneda` también ("ARS", 800 veces). **El modelo no los lee: los emite siempre.** Y la vara son
16 comprobantes que resultan ser todos Transferencia en ARS, así que esos `16/16` son
**32 de 256 campos regalados**. El número que se reporta es **81,7%**.

**Consecuencia de diseño:** mientras la vara sea toda ARS/Transferencia, esos dos campos van a
dar 100% sin significar nada. Reportar siempre el corte sin ellos.

### Lo que sí mejoró de verdad

- **El base dejó de ganar en Mercado Pago.** Era el único corte donde `lora_v3` perdía. Ya no
  hay ningún corte donde convenga el modelo sin entrenar.
- **`nombre_receptor` se arregló**: 1/16 en `lora_v3_final` → 9/16. Era la deuda sin explicación.
- **`cuit_emisor` y `cbu_cvu_emisor` quedaron en 16/16.**
- Empeoraron dos: `concepto` 11→9 y `banco_emisor` 13→11.

⚠️ Cambiaron muchas variables a la vez (dataset 333→842, 80 por banco, etiquetas, 
`train_on_completions`): **la mejora no se puede atribuir a ninguna en particular.**

---

## 3. Los tres errores concretos de monto y fecha

Se fueron a buscar a la base en vez de teorizar:

| Archivo | Verdad | Dijo la IA | Tipo de error |
|---|---|---|---|
| `005.jpeg` | 14.000,00 | 11.300,00 | leyó **otro número** de la pantalla |
| `026.jpeg` | 2026-06-06 | 2026-06-10 | leyó **otra fecha** |
| `044.jpeg` | 28.000,00 · **2023**-06-06 | 1.126.081,9 · **2026**-06-06 | monto tipo CBU + año arrastrado |

**Ninguno es un dígito mal leído: son errores de elegir el campo equivocado.** Eso vive en la
parte de lenguaje —la que el LoRA SÍ entrena— y por lo tanto se corrige con datos y prompt.

⚠️ **Los tres necesitan un ojo humano sobre la imagen y Claude no puede mirarlas** (regla 2: un
comprobante real no sale de la máquina). Preguntas abiertas: ¿aparece "11300" en `005`? ¿tiene
`026` dos fechas? ¿el año de `044` es 2023 o 2026?

---

## 4. 🔴 Los cuatro sesgos del generador — la causa raíz

El usuario sospechó memorización ("pone cosas que no están en el comprobante"). **Tenía razón**,
y se midió exactamente dónde. Todo comparado contra los **2822 movimientos del extracto** y los
**62 comprobantes revisados**, no contra la intuición.

### ① Montos: la distribución estaba invertida

| Dígitos enteros | Sintéticos | Comprobantes reales | Extracto |
|---|---|---|---|
| 4 | 2,9% | 25,8% | **27,9%** |
| 5 | 24,6% | 62,9% | **60,2%** |
| 6 | **72,3%** | 9,7% | 9,6% |

Causa: `random.uniform(500, 350_000)` — al ser uniforme deja el 72% arriba de 100.000. **El
modelo se entrenó esperando cientos de miles donde la realidad son decenas de miles**, y ante una
imagen dudosa cae en ese sesgo: por eso 28.000 salió como 1.126.081,9.

### ② Decimales: 35% terminaba en `,00`, la realidad es 90%

Medido: **90,3% del extracto y 95,2% de los comprobantes no tienen centavos**, 89,4% termina en
`00` y 48,8% en `000`. El generador repartía centavos casi al azar.

### ③ Fechas: una ventana de dos meses

`randint(0, 60)` daba **61 fechas distintas, todas entre 2026-06-12 y 2026-08-11**. El modelo
aprendió el año y el mes en vez de leerlos — **es la explicación del 2023→2026 de `044.jpeg`**.

### ④ Nombres: pools mezclados y largo equivocado

`fake.name()` en es_AR devuelve **3 y 4 palabras** ("Thiago Lionel Ledesma Herrera"), metiendo
nombres de pila en posición de apellido ("Benjamin" aparecía 77 veces como apellido).

⚠️ **Acá se cometió y se corrigió un error de método:** se asumió que los nombres reales eran de
2 palabras y se "arregló" a 2. Al medirlos resultó lo contrario — **son más largos**: 3 palabras
49,1% y 5 palabras 31,5%. Se rehízo apuntando a la distribución medida. **La suposición sobre los
datos hay que confirmarla ANTES de escribir el fix, no después.**

### El resultado, verificado

| | Generado | Real |
|---|---|---|
| Montos de 5 dígitos | 60,2% | 60,2% |
| Montos sin centavos | 89,7% | 90,3% |
| Nombres de 3 palabras | 51,3% | 49,1% |
| Nombres de 5 palabras | 30,8% | 31,5% |

**Lo que NO estaba sesgado:** `monto` tenía 787 valores distintos de 800 y los CUIT/CBU todos
distintos. **La memorización era de la FORMA, no de los valores.**

### Decisión del usuario: `moneda` y `tipo_operacion` se dejan constantes

Se le advirtió que el modelo no puede decir USD ni aunque lo vea, y que la bitácora tenía anotado
lo de la moneda como el peor agujero del motor. **Decidió que está bien que se repitan** porque
todo lo que procesa son transferencias en pesos. Se ejecuta así.

---

## 5. `--desde`: seguir entrenando un adaptador sobre datos nuevos

`--continuar` es **reanudar**, no *seguir entrenando*: lee `estado.json`, ve *paso 841 de 842* y
no da ni un paso con un dataset nuevo. Se agregó `--desde DIR` (~25 líneas en `entrenar.py`):

- Carga los pesos de otro adaptador con **el mismo chequeo de nombres de tensores** que
  `--continuar` (sin él, `strict=False` cargaría cero tensores y entrenaría desde random **sin
  un solo error**).
- Deja el contador en 0 y **el optimizador limpio a propósito**: los momentos de Adam están
  calibrados para el lr y los gradientes de la corrida vieja.
- Rechaza `--desde` + `--continuar`, `--desde == --salida`, y un DIR sin `adapters.safetensors`.
  Las tres validaciones fallan **antes** de los 2 minutos de carga del modelo.

⚠️ **Continuar obliga a mantener `rank 16` y `alpha 0.1`** — el adapter tiene que tener la misma
forma. O sea que "más capacidad" y "sumar el encoder visual" **no se pueden hacer continuando**:
requieren arrancar de cero.

---

## 6. La memoria decide el reloj — otra vez

`lora_v4_v2` arrancó a **86-133 s/paso con el cómputo mismo en 83-152 s**, contra los 24 s de
`lora_v4`. Se descartó el dataset midiendo los tokens de imagen: **mediana 1305 en los dos**,
idénticos. La causa era **memoria libre 33% contra 72%**, con Safari, VS Code, WhatsApp, el
servidor web y Postgres abiertos.

**El efecto es de 3x en el reloj**: 39 h contra ~14 h para los mismos 1642 pasos.

---

## 7. Lo que quedó corriendo

```bash
ia/entrenar.py --dataset ia/sinteticos/train_v5.jsonl --desde ia/checkpoints/lora_v4 \
  --lr 5e-5 --alpha 0.1 --rank 16 --canario 25 --cada 5 --salida ia/checkpoints/lora_v4_v2
```

- `train_v5.jsonl` = **1642 ejemplos** (1600 sintéticos nuevos + 42 reales). `train_v4.jsonl`
  quedó intacto.
- **La vara se verificó IDÉNTICA** byte a byte contra `test_reales.jsonl`: la medición de
  `lora_v4_v2` va a ser comparable con la de `lora_v4`.
- **El dataset está mezclado**: los primeros 200 ejemplos ya cubren los 10 bancos de forma
  pareja. Por eso **cortar antes de terminar es válido** — no deja bancos afuera.
- `--cada 5` rompe a conciencia el ⛔ de la bitácora, con el dato de §1 sobre la mesa.
- `lr 5e-5` (la mitad del original) porque hay que **corregir** un sesgo aprendido, no pulir.

**Antes de generar se dejó un manifiesto de las 800 imágenes viejas y se verificó después que
estuvieran las 800, byte a byte.** Los nombres llevan hash, no colisionaron. (Precaución por el
borrado de las 1364 del 11-ago.)

---

## 8. Lo que quedó abierto

- **Mirar `005.jpeg`, `026.jpeg` y `044.jpeg`** — §3. Es lo que decide si son alucinaciones o
  errores de campo.
- **La verdad tiene `tipo_operacion` escrito de tres formas**: `Transferencia` (50),
  `transferencia_saliente` (11), `Transferencia enviada` (1). El generador ya está alineado; la
  verdad no.
- **La base dice 62 comprobantes revisados y la bitácora decía 58.** Hay que saber cuál es el
  bueno antes de reportar cualquier métrica.
- **Nada está commiteado**: `ia/generar.py` y `ia/entrenar.py` tienen cambios en el working tree.

### Sugerencias medidas, no ejecutadas

1. **Dígito verificador de CUIT y CBU.** El CUIT tiene uno (módulo 11) y el CBU tiene dos. Hoy
   `revision.ts:73-76` valida solo la **cantidad** de dígitos. Con el checksum se **detecta** un
   número mal leído sin tener la verdad al lado, y muchas veces se **corrige** (una sola de las
   ~200 sustituciones de un dígito pasa el verificador). **Es código puro y ataca directamente el
   error que reportó el usuario** (un CBU terminado en 87 que era 88).
2. **Probar el base a 8 bits contra 4 bits**, sin entrenar, ~20 min. El modelo es
   `Qwen2-VL-7B-Instruct-4bit` y la cuantización agresiva es justo lo que degrada la lectura de
   dígitos chicos. **Nunca se probó otra cosa.**
3. **El encoder visual sigue sin entrenarse** (`get_peft_model` recorre solo `language_model`).
   Es el techo de los errores de dígito y **no se arregla continuando**: pide una corrida de cero.
