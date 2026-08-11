# Bitácora

Diario entre sesiones. El proyecto es multi-sesión: sin esto, cada sesión arranca de cero.

**Este archivo es lo único que se lee al empezar.** Tiene el estado, el mapa del código, el
entorno y el índice. El relato de cada sesión vive en `.claude/bitacora/` y **se lee solo si
algo de acá manda a leerlo**. Si este archivo pasa de ~250 líneas, algo que debía mudarse se
quedó.

---

# ⏭️ ESTADO ACTUAL — leer esto primero

**Última actualización:** 2026-08-11, sesión 12.

```bash
# 1. Postgres NO arranca solo al prender la Mac
nc -z localhost 5432 && echo "arriba" || open -a Postgres     # y darle "Start"
# 2. Que todo siga sano  ·  3. Levantar
cd web && pnpm test        # 157 en verde
cd web && pnpm dev         # localhost:3000
# 4. ¿Hay un entrenamiento vivo? El `bash -c` y el `caffeinate` que lo envuelven
#    LLEVAN ADENTRO el texto del comando, así que casi todo grep los cuenta de más.
#    ⛔ `pgrep -f entrenar.py` da de más. ⛔ `grep -cE '[p]ython.*entrenar\.py'`
#       TAMBIÉN da de más (probado 2026-08-10: devolvió 3 con UN solo entrenamiento).
#    ✅ el único que da bien — excluye los envoltorios por nombre:
ps -eo command | grep -E '[e]ntrenar\.py' | grep -vcE '^(bash|caffeinate|/bin/zsh)'
```

🔭 **No hay nada corriendo.** `lora_v3` terminó las 333 pasos el 2026-08-10 20:29 y **ya está
medido** — ver la sección 🎯. Lo siguiente es un experimento nuevo, no esperar nada.

⚡ **Antes de lanzar cualquier entrenamiento: `pmset -g batt | grep "AC Power"`.** A batería
la Mac duerme y no hay flag que lo evite: una calibración hizo **9 pasos en 12 horas** por
esto. Y siempre `nohup caffeinate -dims ... < /dev/null & disown`.

**Releer la regla 1 de `CLAUDE.md`:** antes de cada paso se explica qué se va a hacer y se
espera confirmación. Las autorizaciones no sobreviven al fin de la sesión que las dio.

## 🔄 El plan cambió — `bitacora/reespecificacion.md` manda

El 2026-08-07 el usuario consultó con la empresa y cambió el alcance y el orden. Ese archivo
manda sobre buena parte de `PLAN.md`. **Leerlo antes de planificar cualquier cosa.** En corto:
la IA tiene que sacar **los 16 campos**, la cascada real es **nro de transacción + CUIT → 90%**
y si no **fecha + monto → 50%**, `motor.ts` se reescribe con esa cascada y con TDD, y Looker
Studio entra **solo con métricas del modelo y datos sintéticos**.

> **La prioridad, en palabras del usuario:** *"Concentrémonos en sacar todo del comprobante,
> que es lo más importante. Lo demás solo es lógica de comparación matemática."*

## Dónde estamos

```
F0 ✅  F1 ✅  F2 ✅  F3 ✅  F4 ✅  F5 ✅     BLOQUE A — la conciliación
F6 ✅  F7 ✅  F8 ✅  F9 ✅  F10 🟡           BLOQUE B — la IA
F11 ⬜  F12 ⬜                              BLOQUE C
```

**F9 cerrado el 2026-08-10:** `lora_v3` entrenó las 333 pasos sin colapsar y está medido.
F10 en curso: el número es bueno, falta `lora_v4` para confirmarlo.

En la base real: **2822 movimientos** · **71 comprobantes** (51 reales + 20 sintéticos) ·
**55 revisados a mano** · 8 corridas con su linaje · 256 extracciones.

**La verdad de referencia son los 51 reales revisados a mano, y es lo más valioso del
proyecto**: sin ella no se mide un solo acierto y rehacerla cuesta horas de una persona. Todo
lo que la escribe (`/revisar`, `lib/revision.ts`) se trata en consecuencia.

✅ **LA VERDAD ESTÁ REPASADA ENTERA — 51/51, el 2026-08-11.** Tenía errores: 9 comprobantes con
el CUIT del receptor mal escrito y uno con un CBU guardado en el campo del CUIT. El usuario los
corrigió uno por uno. Al cerrar: **0 CUIT fuera de 11 dígitos, 0 CBU fuera de 22, y 0 usos de
"Guardar igual"** — o sea que ninguno se dio por bueno sin arreglar.

**Corregirla movió la medición varios puntos, a favor del LoRA.** Es la primera medición del
proyecto sobre una verdad verificada dos veces. Cómo se llegó:
`bitacora/sesion-12-mayusculas-y-repaso.md`.

```sql
-- que siga estando sana (los tres tienen que dar 0):
WITH r AS (SELECT * FROM comprobante WHERE revisado_en IS NOT NULL AND corrida_base <> 'sintetico')
SELECT count(*) FROM r WHERE cuit_receptor IS NOT NULL
  AND regexp_replace(cuit_receptor,'\D','','g') !~ '^\d{11}$';
```

⚠️ **Un pendiente de 10 segundos:** el comprobante **126 (`044.jpeg`)** tiene
`cuit_receptor = 20-11260819-9`, y los otros de esa familia son `20-11126081-9`. Los dígitos no
coinciden (`20112608199` vs `20111260819`): parece una transposición. **Es el único CUIT de
receptor que no matchea con ningún otro.** Puede ser una cuenta distinta y estar bien.

**Al comparar se pliegan mayúsculas** (decisión del usuario, 11-ago). Vive en
`normalizarCampo`, **nunca en `paraColumna`**: la base guarda lo que tipeó la persona. También
en `/encontrar` y en el COELSA de `motor.ts`.

## ⛔ `lora_v1` y `lora_v2` están rotos — causa cerrada: `alpha`

Devuelven un chorro de comillas, 0 campos de 256. **Ninguno sirve.** En mlx-vlm `alpha` es la
**escala DIRECTA** (default 0,1), no la de PEFT: con 32 quedaba 320× y el modelo convergía a
repetir un token con la loss bajando igual. **Una métrica de entrenamiento no valida una
capacidad que no mide** — la frase del proyecto, confirmada tres veces. ⛔ `--resize` NO era la
causa. Todo en `bitacora/sesion-09-colapso-alpha.md`.

## 🎯 `lora_v3` ESTÁ MEDIDO — y **le gana al base** donde la medición es limpia

333/333 pasos, `alpha 0.1`, `lr 1e-4`. **12 canarios verdes, 0 fallidos: la primera corrida
larga del proyecto que termina entera y sana.** El colapso, como causa de fracaso, está
cerrado. Cómo se entrenó y se midió: `bitacora/sesion-11-medicion-lora-v3.md`.

⚠️ **Los números de abajo reemplazan a los de la sesión 11**, por dos correcciones del 11-ago
(`bitacora/sesion-12-mayusculas-y-repaso.md`): se pliegan mayúsculas al comparar, y el usuario
corrigió errores propios en 12 de los 16 apartados. **Nada medido antes del 11-ago es
comparable con esto.**

Sobre los 16 apartados, 256 campos, **con la verdad ya repasada entera** (2026-08-11). Se
reproduce con `cd web && node --env-file=.env.local comparar-lora.ts`.

| Corte | v1 (base) | `lora_v3_final` |
|---|---|---|
| **Sin `tipo_operacion`** ← el corte limpio | 67,9% | **70,4%** |
| **Sin Mercado Pago** | 53,6% (60/112) | **66,1%** (74/112) |
| **Los 6 de la conciliación** | 76,0% | **82,3%** (79/96) |
| Solo Mercado Pago | **81,9%** | 66,0% |
| Global (arrastra el bug de vocabulario) | **69,5%** | 66,0% |

**El base es un especialista en Mercado Pago y mediocre en el resto; el LoRA es parejo.** Los
16 apartados son **56% Mercado Pago**, así que el global mide sobre todo una entidad.
**Reportar siempre desagregado por entidad.** Fuera de MP son 7 comprobantes: es señal, no
conclusión.

Mejoró justo donde el base inventaba (`cbu_cvu_emisor` 7→12, `cbu_cvu_receptor` 11→15,
`concepto` 4→11) y empeoró en texto (`nombre_receptor` 9→**1**, sin explicación todavía).

### 🟡 SIN DECIDIR — los guiones del CUIT son el mismo problema que las mayúsculas

Medido el 11-ago sobre los campos numéricos de los 16 apartados, ya con la verdad repasada:

| Corrida | Fallos | De esos, **solo separadores** |
|---|---|---|
| v1 (base) | 40 | **0** |
| `lora_v3_final` | 28 | **10** |

```
cuit_emisor    5   20-27705919-4  ≠  20277059194
cuit_receptor  5   20-10409660-4  ≠  20104096604
```

Mismos dígitos, distinta puntuación: **el LoRA pierde ~4 puntos por guiones y el base no pierde
ninguno.** Es idéntico al caso de las mayúsculas, y el criterio del usuario ya está dicho
("lo importante es que ponga los campos en el lugar correcto").

**Propuesta hecha, sin respuesta:** en `normalizarCampo`, comparar `cuit_emisor`,
`cuit_receptor`, `cbu_cvu_emisor` y `cbu_cvu_receptor` **solo por sus dígitos**. ⛔ NO tocar
`coelsa_id` ni `referencia`: son alfanuméricos y sacarles los no-dígitos les borra las letras.
**Conviene decidirlo ANTES de regenerar el dataset y lanzar `lora_v4`.**

### ⛔ Dos descuentos que siguen abiertos

1. **`tipo_operacion` cuenta 0/16 y acertó los 16.** La verdad dice `Transferencia`, el LoRA
   `transferencia_saliente` — el vocabulario del generador sintético. **6,3 puntos regalados.**
   Ya está alineado en `train_v3.jsonl`, así que `lora_v4` nace sin este descuento. Lección:
   **revisar todo campo de vocabulario cerrado antes de creerle a un porcentaje.**
2. **El "mejor" checkpoint era el PEOR:** `media_20` eligió el paso 218 sobre el final.
   **`mejor/` es red de seguridad contra la divergencia, NO un selector de calidad.**
3. La vara usa prompt v1 y el LoRA v3. Cada uno en su mejor configuración, pero es una
   variable mezclada: decirlo siempre al reportar.

### 🔴 El techo está en la librería, no en los hiperparámetros

**El LoRA nunca toca la parte visual:** `get_peft_model` recorre solo `model.language_model` y
`find_all_linear_names` saltea `vision_tower`/`mm_projector`. Se entrena *cómo escribir la
respuesta*, no *cómo ver mejor*. Es el techo de mlx-vlm 0.1.15 y explica el patrón de la
medición: mejora en cadenas numéricas, no en texto que el encoder resolvió mal. El otro techo
—la loss cubría toda la secuencia— **ya está arreglado** (ver abajo). Los dos, en
`bitacora/sesion-11-medicion-lora-v3.md` §6.

### 🐌 Operación de una corrida larga — ya medido, no volver a medirlo

**La memoria decide el reloj:** 136 s/paso con todo abierto contra 17-31 s con la Mac liberada.
Cerrar apps es gratis; chequear `sysctl vm.swapusage` antes de creerle a un cronómetro.
**⛔ No tocar `--cada`:** guardar cada paso NO cuesta tiempo (la sesión 10 anotó lo contrario y
era falso). **Cerrar la terminal es seguro** (`PPID=1`); lo que mata la corrida es apagar,
reiniciar o suspender la Mac. **Al reanudar el canario cuenta los pasos de la corrida en
curso**, no los absolutos, y el log va en `>>`, nunca en `>`. Detalle en las sesiones 10 y 11.

### ✅ Aplicado y verificado el 2026-08-10 — listo para la próxima corrida

`entrenar.py` con **`train_on_completions=True`** (smoke test de 10 pasos, 2 canarios verdes) y
`generar.py` con el vocabulario de `tipo_operacion` alineado a la verdad.

> ⚠️ **Las curvas de loss de acá en adelante NO se comparan con las anteriores.** Con
> `train_on_completions` la CE se suma solo sobre la respuesta pero se divide por toda la
> secuencia: los 0,03-0,06 del smoke test y los 5,0 de `lora_v3` miden cosas distintas.

**➡️ LO PRIMERO DE LA PRÓXIMA SESIÓN, EN ESTE ORDEN.** El repaso de la verdad **ya está
hecho**; lo que queda es un bloqueante y una decisión.

1. **Decidir lo de los guiones** (sección 🟡 de arriba). Cambia la medición, así que va antes
   de fijar cualquier número de `lora_v4`.
2. 🔴 **REGENERAR el dataset con `reales.py`. BLOQUEANTE.** `train_v3.jsonl` tiene las
   etiquetas de ANTES del repaso del 11-ago: entrenar con él es entrenar con los errores que el
   usuario ya arregló. **Sale un `train_v4.jsonl` nuevo y la partición se rehace**, así que hay
   que anotar los 16 apartados que salgan (los imprime el script).
3. **Recién ahí, `lora_v4`.** 333 pasos, ~5 h. Antes: `pmset -g batt | grep "AC Power"`.

⚠️ **Al regenerar cambia la vara.** `reales.py` sortea los 16 apartados con semilla fija sobre
el conjunto de revisados; el conjunto es el mismo (51) pero **las etiquetas cambiaron**, así que
los números de la tabla 🎯 hay que rehacerlos contra el test nuevo antes de comparar nada.

```bash
ia/.venv/bin/python ia/reales.py --sinteticos <sintéticos> \
  --salida ia/sinteticos/train_v4.jsonl --test ia/sinteticos/test_reales.jsonl   # paso 3

nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py \
  --dataset ia/sinteticos/train_v4.jsonl \
  --lr 1e-4 --alpha 0.1 --canario 25 \
  --salida ia/checkpoints/lora_v4 \
  > ia/checkpoints/lora_v4.log 2>&1 < /dev/null & disown
```

**Dos variables cambian a la vez respecto de `lora_v3`** (`train_on_completions` y el
vocabulario) y está asumido a propósito: la segunda es un arreglo de medición, no un
hiperparámetro. De acá en adelante, **una sola por corrida.**

Al terminar, medir igual que el 10-ago — está todo en `bitacora/sesion-11-medicion-lora-v3.md`
sección 3, y `web/comparar-lora.ts` reproduce la tabla con un comando.

### ▶️ Después de esa corrida, por retorno esperado

**Uno por vez y con una sola variable** — así se cerró `alpha`. Ninguno está confirmado.

1. **`lr`**: con la loss dos órdenes más chica, el gradiente también lo es y `1e-4` puede
   quedar corto. Se decide mirando la curva, no adivinando.
2. **`alpha 1.0`**, calibrado en la sesión 10 y nunca usado en una corrida larga.
3. **Más comprobantes reales de fuentes nuevas** + más variedad de sintéticos. El generador ya
   tiene 10 plantillas de banco; lo que no se fabrica es una foto real.
4. **Apartar entidades ENTERAS** del entrenamiento (leave-one-bank-out) en vez de comprobantes
   sueltos: es la única medición que contesta *"¿anda con un banco que nunca vio?"*, que es la
   pregunta de la que depende que el sistema valga algo.
5. Por qué se rompió `nombre_receptor` (9/16 → 2/16).
6. Que el checkpoint lo elija la medición sobre los apartados y no `media_20`.

## 🔧 Estado de las herramientas de IA

- **Usar `ia/sinteticos/train_v3.jsonl` (333).** Es `train_v2_sin_gigantes` con el vocabulario
  de `tipo_operacion` alineado a la verdad; hereda su exclusión de gigantes. ⛔ **NO usar
  `train_v2.jsonl` (335):** sus índices 162 y 278 (`033.jpeg`, `015.jpeg`; ~3078 y ~3534 tokens
  de imagen) **matan el proceso sin dejar traceback** — reproducido en aislamiento. El resto
  tope en 1938 y está probado que 1848 pasa. Por eso murieron las corridas del 7 y del 8,
  **no** por SIGHUP. ⛔ **Nunca `test_reales.jsonl`:** son los 16 de la vara.
- `entrenar.py` guarda **cada paso** (atómico), guarda el **estado de Adam** —sin eso reanudar
  DIVERGE: se perdieron 5 h así— y mantiene el **mejor checkpoint** en `<salida>/mejor/`.
- **Canario** (`--canario 25`): genera de verdad cada N pasos y aborta tras K fallos seguidos.
  Cuesta ~60-110 s por vez (**+3,6%**) y detecta en 40 min lo que costó 7 h y 9 h.
- `extraer.py`: el banner `#trainable params` ya no contamina el JSONL, `parsear()` tolera
  salidas que no son objetos, y `parchear_detokenizador()` evita que **una tilde partida mate
  la corrida entera** (bug de `BPEStreamingDetokenizer`, mlx-vlm 0.1.15).

## 📊 F7 — la medición sobre los 51 (histórica)

v1 65% · v2 43% · v4 41% sobre 816 campos; el 71% de v3 está inflado por construcción. **Son
anteriores al plegado de mayúsculas y a las correcciones del 11-ago: valen para el orden entre
corridas, no como cifras.** Tabla, auditoría y el modo de falla dominante (inventar campos del
emisor: `cbu_cvu_emisor` en 24 de 51) en `bitacora/sesion-07-medicion.md`.

**Lección de prompting (sesión 3, sigue valiendo):** describir qué SÍ va en un campo, **nunca
qué no** — decirle al modelo qué no poner hace que deje de llenarlo.

## ⚠️ El motor no verifica NADA, y tiene 3 agujeros abiertos

`no_verificable 63 · sospechoso 8 · verificado 0`, y **0 CBU propios aprobados**. No es un bug:
`motor.ts` cruza por `cuenta.cbu` y las tres cuentas lo tienen en NULL. `/encontrar` **no usa
`motor.ts`** y por eso funciona igual: implementa la cascada de la empresa (90%/50%) en SQL.

Los tres agujeros, en orden: **(1) el motor no mira la moneda** — un comprobante en dólares
puede dar match falso contra un extracto en pesos, el más grave; **(2) `cbu_cvu_receptor` no
alcanza como identificador** — hace falta la cascada CBU → CUIT → nombre, y el CUIT de cada
cuenta en `cuenta`; **(3) los CBU de las 3 cuentas siguen en NULL** desde la sesión 1.

Los tres tocan `motor.ts`, que la re-especificación manda reescribir entero con TDD. **Sin
decisión del usuario, no se toca.**

## Lo que hace falta del usuario

- **Comprobantes reales de fuentes NUEVAS.** No falta cantidad sino variedad: Nación, Brubank,
  BBVA, Uala, Personal Pay, Naranja X, Cuenta DNI, Prex. Cinco de cinco bancos distintos valen
  más que treinta de Mercado Pago, que ya es el 56% de la vara. **Cada uno necesita revisión
  humana en `/revisar` para servir** — y el pedido de cargarlos a mano choca hoy con la deuda
  🔴 de más abajo
- **Aprobar sus CBU en `/cbu`.** Hay 6 candidatos esperando. **No los siembra Claude**: que la
  IA haya leído un número 20 veces no lo hace correcto
- **Los CUIT de las 3 cuentas.** El extracto trae CUIT en el 98,7% de los ingresos
- **Un caso real** — extracto y comprobantes de la misma fuente y período. Es lo único que
  valida la regla del 90%. Ya confirmó que va a conseguirlo
- **Decidir la meta del 98%.** Sobre los 16 campos no es alcanzable: el techo lo pone
  `concepto`, texto libre. Propuesta sin responder, **con el número del 11-ago**: los 6 que
  deciden la conciliación van **76,0% el base y 82,3% `lora_v3_final`**. Exigir 98% **por
  campo** sobre esos 6 es la métrica correcta
- **Decidir lo de los guiones del CUIT** (sección 🟡). Propuesta hecha, sin respuesta
- **Mirar el comprobante 126** (`044.jpeg`): su CUIT de receptor no matchea con ningún otro
- **Resolver la contradicción de `CLAUDE.md`** sobre la regla 2: en la sesión 3 se miraron 3
  comprobantes con autorización expresa y el documento sigue diciendo que los datos nunca salen
  de la máquina. O se actualiza la regla, o se asienta como excepción
- **Decidir sobre los 3 agujeros de diseño**
- **Plantillas sintéticas de más bancos** — pedido el 11-ago, para después del repaso

## ⛔ Lo que no hay que volver a intentar

**Cruzar los comprobantes con `TRANSFERENCIAS.xlsx`.** Son dos ejemplos sin relación, ya medido:
19 cruzan por monto+fecha y **0 sobreviven al CUIT**. Firma de coincidencias casuales — y la
prueba de por qué la regla del 90% mira el CUIT antes que el importe: sin ese chequeo habría
reportado **19 falsos positivos**.

**Citar con backticks adentro de un template literal de TS.** Corta el string y el error sale
lejos (`Expected ',', got 'revisado_en'`). Pasó dos veces el 11-ago, las dos en comentarios SQL.

---

# 📚 Índice — leer solo lo que haga falta

| Archivo | Qué tiene | Cuándo leerlo |
|---|---|---|
| `bitacora/reespecificacion.md` | El alcance que pidió la empresa, Looker Studio, la premisa del CUIT en `NRO TRANSACCION` que no se verificó | **Antes de planificar cualquier cosa** |
| `bitacora/sesion-12-mayusculas-y-repaso.md` | **Por qué la medición castigaba tipografía y por qué los números anteriores no sirven**, los errores encontrados en la verdad de referencia, el chequeo de forma de `/revisar` con su migración 007, los dos bugs del recorrido, y **los 4 cortes que dejan la carga manual fuera del entrenamiento** | **Antes de tocar la medición, `/revisar` o la carga de comprobantes** |
| `bitacora/sesion-11-medicion-lora-v3.md` | **La medición completa del LoRA** con sus tablas por campo y por entidad, el bug de vocabulario de `tipo_operacion`, por qué el "mejor" checkpoint era el peor, y los dos techos de mlx-vlm (la loss cubre el prompt entero; el LoRA no toca la parte visual) | **Antes de tocar el entrenamiento, el dataset o la medición** |
| `bitacora/sesion-10-probador-web.md` | El cierre de la calibración y por qué la loss no eligió, el costo real de `--cada 1`, la pantalla `/probar` con sus decisiones, y por qué un POST sin JavaScript no puede probar una Server Action | Al tocar `/probar` o el entrenamiento |
| `bitacora/sesion-09-colapso-alpha.md` | **Por qué colapsaron los dos LoRA (`alpha` es escala directa en mlx-vlm)**, el bug del detokenizador que mata una corrida por una tilde, el canario y sus dos versiones equivocadas, y 3 errores de operación | **Antes de tocar el entrenamiento o la medición** |
| `bitacora/sesion-08-checkpoints.md` | El checkpoint por paso y `--continuar`, y por qué cronometrar en MLX engaña. ⛔ **Su diagnóstico (SIGHUP) y su decisión sobre el optimizador son FALSOS** — leer antes la sesión 9 | Solo después de la sesión 9 |
| `bitacora/sesion-07-medicion.md` | Por qué una fecha imposible tumbaba una corrida entera, la auditoría de F7 con su tabla, por qué `acciones.ts` no se podía testear | Al tocar la medición, `/revisar` o lo que escribe la verdad |
| `bitacora/sesion-06-lora-v2.md` | Por qué `lora_v1` salió roto, la curva calidad-vs-tamaño, el dataset de v2, la regla del CBU | **Antes de tocar el entrenamiento o la medición** |
| `bitacora/sesion-05-origen-excel.md` | Hoja y fila real de cada movimiento; el backfill por huella | Al tocar `importar.ts` o `/encontrar` |
| `bitacora/sesion-04-dataset-lora.md` | `ia/generar.py`, los 4 bugs de `mlx-vlm`, `--resize`, el diseño de medición de F10 | Al tocar el entrenamiento o el dataset |
| `bitacora/sesion-03-ia.md` | Los 4 prompts medidos, las trampas de `mlx-vlm 0.1.15` | Al tocar `extraer.py` o los prompts |
| `bitacora/sesion-02-conciliacion.md` | F1 a F5: el parser, el importador, las fixtures, el motor, las 4 pantallas | Al tocar `motor.ts`, `extracto.ts` o la base |
| `bitacora/sesion-01-diseno.md` | El diseño original y los 5 números que resultaron falsos | Casi nunca. Está por trazabilidad |

---

# 🗺️ Mapa del código

```
web/migraciones/001..007.sql          5 tablas + conciliación + revisado_en +
                                      corrida/extraccion + hoja/fila + cbu_propio +
                                      formato_aceptado_en
web/src/lib/db.ts                     el Pool de pg, 4 líneas
web/src/lib/extracto.ts               parser puro: importes, fechas, CUIT, COELSA, huella
web/src/lib/importar.ts               Excel → Postgres. Acepta ruta o Buffer
web/src/lib/importar-comprobantes.ts  JSONL → base. Exporta `normalizarCampo` (compara, y
                                      PLIEGA mayúsculas) y `paraColumna` (guarda, y NO pliega)
web/src/lib/revision.ts               lo que escribe una PERSONA: corregir y cargar a mano.
                                      Además `motivosDeFormato` (CUIT 11 / CBU 22 / "null"),
                                      `cola`+`entra` (los filtros de /revisar) y `proximo`
web/src/lib/motor.ts                  la cascada vieja. Lógica pura, sin base ni red
web/src/lib/conciliacion.ts           puente motor ↔ base + queries del tablero
web/src/lib/fixtures.ts               14 comprobantes con su respuesta conocida
web/src/app/                          las 8 pantallas + acciones.ts (Server Actions)
web/src/app/probar/                   subir foto → 16 campos. Corre ia/extraer.py, sin base
web/comparar-lora.ts                  compara corridas sobre los MISMOS comprobantes, con
                                      cortes por entidad y por campo. Reusa normalizarCampo

ia/extraer.py     inferencia local. Prompts v1/v2/v3, rescata JSON truncado. Con --adaptador
ia/entrenar.py    LoRA sobre mlx-vlm, los 5 bugs esquivados + checkpoint por paso y --continuar
ia/generar.py     dataset sintético. Etiqueta canónica, imagen realista. verificar(): 7 asserts
ia/reales.py      la verdad corregida → JSONL, con la partición train/test
ia/validar.py     separa lo confiable de lo que va a carga manual
ia/calidad.py     mide formato y compara dos corridas. Nunca imprime valores
ia/comprobantes/  los 51 reales, copiados de viejo/ y renumerados

ia/sinteticos/train_v3.jsonl              ⬅️ EL DATASET A USAR (333, vocabulario alineado)
ia/sinteticos/train_v2_sin_gigantes.jsonl    el anterior. Solo como evidencia, NO entrenar
ia/sinteticos/test_reales.jsonl           los 16 apartados con su verdad. NUNCA entrenar
ia/salida_lora_v3_{mejor,final}.jsonl     las extracciones ya medidas del 10-ago
```

**El modelo de datos que importa:** `extraccion.campos` es lo que contestó el modelo por corrida
y **nunca se pisa**; las columnas tipadas de `comprobante` son la verdad, arrancan iguales y las
corrige una persona; `comprobante.corrida_base` dice contra cuál se compara. Qué campos estaban
mal **no se guarda**: sale de comparar los dos.

⚠️ **`paraColumna` es el único camino** por el que un campo crudo se convierte a su columna. La
usan `normalizarCampo`, el importador, `/revisar`, la carga manual y la tabla de aciertos. Tienen
que usar todos el mismo o vuelven los falsos "corregidos" que metían errores inventados en los
números del informe.

⚠️ **Nada de `lib/` puede importarse desde un componente cliente**: arrastra `pg`. Los
`'use client'` reciben todo calculado por props (ver `revisar/[id]/formulario.tsx`).

**Las 8 pantallas:** **`/probar` subir una foto y ver los 16 campos** — no escribe en la base,
la imagen se borra al terminar; selector de adaptador que se llena solo desde
`ia/checkpoints/` · `/` tablero con los 6 estados, su conteo, su explicación, filtro y
Recalcular · `/extracto` subir el Excel y ver el resumen por cuenta · `/comprobante` carga a
mano, imagen + los 16 campos agrupados · `/resolver` los ambiguos con sus candidatos al lado ·
**`/revisar` la corrección humana**, imagen izquierda / 16 campos derecha, cuatro filtros
(pendientes · revisados · **con dudas** · todos), botón *Revisar N de corrido*, y al guardar
**salta al siguiente del mismo filtro** salvo que algún campo tenga forma imposible: ahí se
queda, avisa cuál, y ofrece *Guardar igual* · `/encontrar` qué hoja y fila del Excel le toca a
cada comprobante, por qué regla, y el **export a Excel con colores** ·
**`/cbu` los CBU/CVU propios**: un receptor que no esté acá deja al comprobante como
*transcripción dudosa*.

⚠️ **La cola de `/revisar` se ordena SOLO por `id`.** Cualquier orden que dependa de
`revisado_en` se reordena al guardar y "el que sigue" pasa a ser otro en cada guardado.

---

# 🔧 Datos del entorno

```bash
# Postgres 18.4 (Postgres.app) — psql NO está en el PATH, por decisión
/Applications/Postgres.app/Contents/Versions/18/bin/psql -d conciliador
DATABASE_URL=postgresql://luisparmigiani@localhost:5432/conciliador   # en web/.env.local

cd web && pnpm dev         # localhost:3000 — SIEMPRE pnpm, nunca npm
cd web && pnpm test        # node --test, sin framework. 157 en verde
cd web && pnpm db:test:reiniciar                  # recrea conciliador_test desde cero
cd web && pnpm importar ../TRANSFERENCIAS.xlsx    # Excel → base REAL. Reimportar es seguro
cd web && pnpm importar:comprobantes ../ia/salida.jsonl <corrida> [flags]

# la IA, siempre local — nada sale de la máquina
ia/.venv/bin/python ia/extraer.py ia/comprobantes/*.jpeg > salida.jsonl   # ~15-30 min los 51
ia/.venv/bin/python ia/validar.py salida.jsonl validado.jsonl
ia/.venv/bin/python ia/calidad.py viejo.jsonl nuevo.jsonl
```

⚠️ **`pnpm db:migrar` NO se puede correr sobre la base real.** La 001 y la 002 no son
idempotentes (`ADD COLUMN` pelado). Para una migración nueva:
`psql -v ON_ERROR_STOP=1 -d conciliador -f migraciones/00N_loquesea.sql` con el binario de arriba.

**Dos bases, a propósito.** `conciliador` tiene los **2822 movimientos reales** (2526 ingresos,
296 egresos) + 71 comprobantes; `conciliador_test` es fabricado y descartable, y lo toca solo
`pnpm test`. El `DATABASE_URL` de test está en el script `test` de `package.json`, a la vista:
los tests no llegan a la base real ni por accidente. Ninguna migración lleva `DROP TABLE`.

Node 24.12.0 · pnpm 10.27.0 · Next 16.3.0 · React 19.2.8 · Tailwind 4.3.3 · TS 5.9.3.
**Sin repo git** — el usuario lo crea aparte; el `.gitignore` de la raíz ya cubre lo sensible.

**Notas de Next.js 16 que costaron tiempo** (las de `params`/`searchParams` como Promises y
`force-dynamic`, en `bitacora/sesion-02-conciliacion.md`): `PageProps<'/ruta'>` y
`RouteContext<'/ruta'>` **los genera Next** — al crear una ruta nueva `tsc` falla hasta correr
`pnpm exec next typegen` · para devolver un error **sin perder lo tipeado** hace falta
`useActionState`, o sea un componente cliente: un `redirect()` pierde el formulario entero.

---

# 📋 Deudas técnicas conocidas (ninguna bloquea)

| Deuda | Detalle |
|---|---|
| 🔴 **Un comprobante cargado a mano NUNCA llega al entrenamiento** | Cuatro cortes y ninguno avisa: la imagen va a `web/comprobantes/` pero el visor solo mira `ia/comprobantes/` (⇒ **404 en `/revisar`**); `reales.py:56` filtra `corrida_base <> 'sintetico'`, que en SQL da **NULL** cuando la columna es NULL, y un manual la tiene NULL; y `cargarComprobante` no escribe `revisado_en`. Hoy no rompe porque los 71 son `origen='ia'`. **El usuario quiere cargar reales para entrenar: arreglarlo antes.** Plan escrito en `bitacora/sesion-12-mayusculas-y-repaso.md` §5 |
| `nombre_receptor` se derrumbó con el LoRA | 9/16 el base contra **1/16** `lora_v3_final`. Sin explicación. Es el único campo donde el LoRA es peor por goleada |
| **`oNulo` no atrapa el string `'null'`** | Trata `''` y `'N/A'` como ausencia, pero el modelo devuelve las tres. Medido sobre los 51: son aciertos contados como errores en **4 (v1) · 4 (v2) · 5 (v3) · 7 (v4)** campos de 816. v1 pasaría de 65,2% a 65,7%. **No cambia el orden ni ninguna conclusión**, por eso no se tocó: arreglarlo mueve todos los números publicados y se decide a propósito. Hay 3 filas de `comprobante` con `'null'`/`'N/A'` guardado como valor. `/probar` ya lo muestra como ausencia |
| `corridas/page.tsx:85` cuenta blobs de JSON, no comprobantes | Latente: hoy da 55 por los dos caminos. Miente el día que haya dos revisados con los 16 campos idénticos |
| Ese "55 revisados" mezcla 51 reales + 4 sintéticos | Los denominadores por corrida están bien (51 en v1–v4): los porcentajes del informe están sanos |
| Los 20 sintéticos cargados tienen las etiquetas ROTAS | Vienen del generador que inventaba campos. **Hay que recargarlos** desde el dataset nuevo |
| `@types/node` en `^20`, runtime Node 24.12 | `import.meta.main` y el `Buffer` de `exceljs` necesitan un cast local |
| Warning `MODULE_TYPELESS_PACKAGE_JSON` en `pnpm test` | Es de performance. Se va con `"type": "module"` |
| No se usó `ui-ux-pro-max` en las pantallas | F5 pide sin dashboard ni gráficos, que es lo que esa skill optimiza. Queda a mano |
| 96 movimientos (3,4%) con `tipo` NULL | A propósito: nunca se cruza por `tipo` |
| Mojibake en las descripciones (`COMPENSACIàN`) | Viene del origen. No se corrige: sería adivinar |
| Variedad de tipeo en la verdad (`"Mercado Pago"` / `"mercado pago"`) | Medido: **no cambia ningún acierto**. Hay un test que fija que NO se pliegan mayúsculas solas |
| **`BITACORA.md` sigue arriba del techo: 467 líneas contra ~250** | La pasada del 11-ago comprimió a punteros F7, el motor, los 3 agujeros, los techos de la librería, la operación de una corrida larga y el colapso de v1/v2 — pero el estado de la sesión 12 sumó más de lo que se sacó. **Lo que quedó largo es el ESTADO ACTUAL, que es justo lo que hay que leer.** El recorte real llega cuando `lora_v4` cierre F10: ahí la sección 🎯 entera, la 🟡 y la cola de experimentos se mudan a su archivo de sesión |
| **Se pueden borrar:** `duplicadas_para_revisar.csv`, `ia/checkpoints/lora_bancos.safetensors` (154 MB) + su `adapter_config.json`, `ia/verdad_referencia.xlsx`, **`ia/checkpoints/smoke_completions/` (462 MB)** | Sobrantes del análisis de duplicadas, del smoke test de F9, de la verdad que reemplazó `/revisar`, y del smoke test de `train_on_completions` del 10-ago — **su log alcanza como evidencia, los pesos de 10 pasos no sirven para nada** |
| **Se conservan como evidencia:** `ia/salida_v2.jsonl` vs `..._rescatado.jsonl`, `ia/sinteticos/train_v1_ROTO.jsonl`, `ia/checkpoints/lora_v1/` | Permiten reproducir el error metodológico, las etiquetas inventadas y la curva de una corrida colapsada |

# ❓ Preguntas de diseño que siguen abiertas

- **La API de deudas (F12)**: qué API es, qué expone, en qué dirección va la información
- **Autoconfirmar la extracción de la IA (F11)** solo se habilita para los campos que F10
  demuestre que lo merecen. Antes no
