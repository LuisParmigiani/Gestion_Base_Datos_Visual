# Sesión 16 — `lora_v4_v2` terminado y medido, y los CSV de Looker Studio

**2026-08-14 / 15.** Se reanudó la corrida que había muerto, terminó, se midió, y se armaron
los tres CSV del tablero. Además se reescribió el `README.md` entero y se verificaron contra
la base los conteos que la bitácora venía arrastrando.

---

## 1. Por qué se había muerto: la Mac se apagó

La corrida estaba en el paso 1099 y el log terminaba con un warning de `resource_tracker`, que
no dice nada por sí solo. La causa salió de `last`:

```
shutdown time    Fri Aug 14 08:13
reboot time      Fri Aug 14 09:10
```

**No fue OOM ni sueño**: el `caffeinate` estaba activo hasta el final (se ve en `pmset -g log`,
sus assertions siguen hasta las 08:10) y no hay un solo evento de `jetsam` en el rango. La
máquina se apagó, que es el único escenario que la bitácora marca como fatal.

**El checkpoint estaba sano**, y eso se verifica antes de reanudar, no después:

```
adapters.safetensors     392 tensores · meta paso=1094
optimizador.safetensors  786 tensores · meta paso=1094   ← coinciden
```

El `adapters.tmp.safetensors` de 0 bytes que había quedado es residuo inofensivo: el guardado
es atómico con `os.replace`, así que un kill en mitad de la escritura deja intacto el
checkpoint anterior.

### ⚠️ Al reanudar hay que repetir TODOS los hiperparámetros

`--continuar` lee el `estado.json` **solo** para el contador de pasos y el estado de Adam. Los
flags salen de `argparse`, así que si no se pasan toma los defaults —`--lr 2e-5` y
`--dataset train.jsonl`— y **sigue entrenando con otro dataset sin decir una palabra**. El
comando correcto quedó en el README.

---

## 2. Reanudación y final

Reanudó limpio en el paso 1096, con el estado de Adam restaurado:

```
continuando desde epoch 0, paso 1096 (último loss 0.0000, guardado 2026-08-14 08:02:39),
con el estado de Adam restaurado.
mejor checkpoint previo: media_20 0.001
```

**Final: 547 pasos en 1031,2 min (17,2 h) a 113,1 s/paso. 1642/1642. 0 canarios fallidos.**

### 🔴 La memoria NO explicó el reloj esta vez

La bitácora dice que con ~72% de memoria libre el ritmo es de 24-31 s/paso. **Se midió 71%
libre y 122 s/paso.** El ritmo real, medido con `ps -o etime` entre hitos de 100 pasos:

| Tramo | s/paso reales | s/paso del cronómetro interno |
|---|---|---|
| 1101 → 1201 | 122 | ~96 |
| 1201 → 1301 | 108 | — |
| 1301 → 1401 | 107 | — |
| 1401 → 1501 | 107 | — |
| **Toda la reanudación** | **113,1** | — |

**La regla "la memoria decide el reloj" no es universal.** Acá el gap entre los ~96 s internos
y los 113 reales sale del guardado de 484 MB cada 5 pasos más el canario cada 25 — que es la
otra causa que la sesión 15 ya había distinguido (`§1`: si `dt` sube es memoria, si `dt` está
bajo y el reloj alto es el guardado). Este caso fue el segundo.

⛔ **Se confirma una vez más: para estimar una corrida, `ps -o etime`. Nunca la curva.**

---

## 3. La medición: `lora_v4_v2` gana por 0,9 puntos

`extraer.py --adaptador ia/checkpoints/lora_v4_v2 --prompt v3` sobre los 16 apartados →
importado como `lora_v4_v2_final` → `comparar-lora.ts`.

| Corte | base v1 | `lora_v3_final` | `lora_v4_final` | `lora_v4_v2_final` |
|---|---|---|---|---|
| Global (inflado) | 69,5% | 69,9% | 84,0% | 84,8% |
| Sin `tipo_operacion` | 67,9% | 74,6% | 82,9% | 83,8% |
| **Sin `tipo_operacion` NI `moneda`** ← el honesto | 66,1% | 72,8% | 81,7% | **82,6%** |
| Sin Mercado Pago | 53,6% | 67,9% | 80,4% | 80,4% |
| Solo Mercado Pago | 81,9% | 71,5% | 86,8% | **88,2%** |
| **Los 6 de la conciliación** | 76,0% | 87,5% | **91,7%** | 90,6% |

### Por campo, contra `lora_v4`

| Campo | `lora_v4` | `lora_v4_v2` | |
|---|---|---|---|
| `concepto` | 9/16 | **12/16** | +3 |
| `nombre_receptor` | 9/16 | 10/16 | +1 |
| `hora` | 15/16 | **16/16** | +1 |
| `banco_emisor` | 11/16 | 12/16 | +1 |
| `cbu_cvu_emisor` | **16/16** | 14/16 | **−2** |
| `nombre_emisor` | 13/16 | 12/16 | −1 |
| `referencia` | 13/16 | 12/16 | −1 |
| `monto` · `fecha` | 14/16 | 14/16 | **sin cambio** |

### 🔴 Lo más importante de esta medición: los sesgos corregidos no movieron `monto` ni `fecha`

Los cuatro sesgos que la sesión 15 encontró y corrigió eran los de **monto, decimales, fecha y
nombres**. La corrección era correcta —está medida contra los 2822 movimientos del extracto, no
supuesta— y sin embargo `monto` y `fecha` quedaron **idénticos en 14/16**.

Dos explicaciones posibles, y no se pueden separar con lo que hay:

1. **La vara es demasiado chica.** 16 comprobantes × 1 campo = 16 observaciones por campo. Para
   ver un efecto de pocos puntos hace falta más.
2. **Los 2 que fallan no fallan por la distribución** sino por lectura visual — y el LoRA no
   toca el encoder visual.

**Lo que lo destrabaría:** medir sobre más comprobantes reales. Es la misma conclusión a la que
llegó la sesión 15 por otro camino.

### ⚠️ Bajó en el corte que más importa

91,7% → 90,6% en los 6 campos de la conciliación. **La diferencia es un solo campo**
(`referencia`), y sobre 96 campos un acierto vale 1,04 puntos: está dentro del ruido de esta
vara. Pero es el corte que decide y se reporta igual.

### ⚠️ Cambió dos variables a la vez

`train_v5` (dataset nuevo) **y** `lr` 1e-4 → 5e-5. Los +0,9 puntos no se pueden atribuir a
ninguna de las dos. Es justo lo que la cola de experimentos dice no hacer.

---

## 4. Los CSV de Looker Studio

Decisión del usuario: usarlo para la **comparativa entre modelos**, que no toca ningún dato
bancario. Se mantiene la decisión de `reespecificacion.md` de no conectar Postgres.

| Archivo | Filas | Lo genera |
|---|---|---|
| `metricas/extraccion.csv` | 1792 | `comparar-lora.ts` (modificado) |
| `metricas/curvas_loss.csv` | 3550 | `ia/metricas.sh` (nuevo) |
| `metricas/corridas.csv` | 6 | A mano |

### Por qué UN CSV largo y no uno por corte

`extraccion.csv` tiene una fila por **corrida × comprobante × campo** con `acierto` 0/1. Con
esas cuatro dimensiones el tablero calcula cualquier corte solo, y la métrica es siempre
`AVG(acierto)`. Exportar un CSV por vista obligaría a mantener los mismos cortes en dos lugares.

**Se validó reproduciendo los números históricos desde el CSV con un `awk`**: 81,7% para
`lora_v4`, 72,8% para `lora_v3`, 66,1% para el base. Coinciden exactos con los de la sesión 15.

### `corridas.csv` se escribe a mano, a propósito

Son 6 filas y contienen datos que **no están en ningún log**: el `alpha` de las primeras
corridas y el veredicto "roto". Parsear logs heterogéneos para eso sería más máquina que
problema.

### `.gitignore`: excepción acotada

La línea 5 es `*.csv`, así que `metricas/` no entraba a git. Se agregó `!metricas/*.csv` y se
verificó que la excepción **no** se derrama: `duplicadas_para_revisar.csv` y cualquier `.csv`
en otra carpeta siguen ignorados.

### ⛔ La página 3 del tablero no se puede armar todavía

El demo del tablero de conciliación necesita datos que hoy no existen usables: `motor.ts`
devuelve `no_verificable` en los 69 (CBU en NULL) y los 20 sintéticos cargados tienen las
etiquetas rotas. Un tablero de los seis estados saldría con **una sola barra**. Está anotado en
`metricas/LEEME.md`.

---

## 5. Conteos verificados contra la base

La bitácora venía arrastrando números sin confirmar. Se consultaron todos:

| Dato | Decía | Es | |
|---|---|---|---|
| Revisados | "58 o 62, en disputa" | **62 y 58** | ✅ resuelto, ver abajo |
| CBU propios | "6 candidatos esperando" | 8 candidatos, 5 aprobados, **3 pendientes** | corregido |
| Corridas | 9 | **10** (279 extracciones) | corregido |
| Movimientos · ingresos | 2822 · 2526 | 2822 · 2526 | ✅ |
| Comprobantes | 78 | 78 | ✅ |
| Elecciones humanas | 37 | 37 | ✅ |
| Cuentas con CBU | 0 | 0 | ✅ |

### ✅ La duda del "¿58 o 62?" era una pregunta mal hecha

Los dos números son correctos y miden cosas distintas:

```sql
revisado_en IS NOT NULL                                  -- 62  (incluye 4 sintéticos revisados)
revisado_en IS NOT NULL AND corrida_base <> 'sintetico'  -- 58  (los reales)
```

El segundo es el filtro de `reales.py:CONSULTA`. **58 es el número a reportar** cuando se habla
de la verdad de referencia; 78 = 58 reales + 20 sintéticos, y de esos 78 hay 62 revisados.

---

## 6. Un tropiezo: `importar:comprobantes` sin `--imagenes`

La primera importación devolvió `sin imagen 16` y no insertó nada. Causa: `extraer.py` escribe
`archivo: "002.jpeg"` sin ruta, y el importador lo resuelve contra el directorio del JSONL
(`ia/`), no contra `ia/comprobantes/`.

```bash
# mal — resuelve contra ia/
pnpm importar:comprobantes ../ia/salida_lora_v4_v2_final.jsonl lora_v4_v2_final ...
# bien
... --imagenes ../ia/comprobantes
```

Con el flag: `comprobantes nuevos 0 · extracciones nuevas 16`, que es exactamente lo correcto —
los 16 ya existían y se matchearon por `hash_imagen`.

⚠️ **Nunca con `--base`** al medir: ese flag siembra `corrida_base` y pisaría la verdad.

---

## 7. `README.md` reescrito entero

Estaba desactualizado en cosas grandes: decía que el fine-tuning no había empezado, hablaba de
4 pantallas y de 52 comprobantes, y **no mencionaba una sola de las 9 tablas**.

Ahora tiene, además de lo que ya estaba: **el modelo de datos completo** (las 9 tablas con cada
atributo, sus relaciones y el porqué de cada decisión de diseño) y **el informe de
entrenamiento** (por qué LoRA, el dataset, los 5 parches a `mlx-vlm`, las 6 corridas, la
medición y los techos).

Verificado que no lleva un solo dato real: 0 CUIT, 0 CBU, 0 COELSA. **Se sacaron también los
nombres de las tres hojas del extracto**, que el README viejo publicaba y están en git.

---

## 8. Lo que queda de esta sesión

- **Commitear.** Lo hace el usuario. Sin commitear: `ia/generar.py` y `ia/entrenar.py` (desde el
  13-ago), `ia/metricas.sh`, `metricas/*`, `README.md`, `web/comparar-lora.ts`, `.gitignore`.
- **La cola de experimentos** se mudó acá desde `BITACORA.md`. Ninguno confirmado, **uno por vez
  y con una sola variable**:
  1. **Más comprobantes reales de bancos nuevos.** Subió al primer puesto: es lo que destraba la
     medición de `monto`/`fecha` y lo único que no se fabrica.
  2. **`lr`**: con la loss dos órdenes más chica, `1e-4` puede quedar corto.
  3. **`alpha 1.0`**, calibrado en la sesión 10 y nunca usado en una corrida larga.
  4. **Leave-one-bank-out**: apartar entidades enteras. La única medición que contesta *"¿anda
     con un banco que nunca vio?"*.
  5. Por qué `cbu_cvu_emisor` perdió el 16/16 que tenía en `lora_v4`.
- **Que el checkpoint lo elija la medición y no `media_20`** — `mejor/` es red contra la
  divergencia, **NO un selector de calidad**.
