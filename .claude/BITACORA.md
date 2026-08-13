# Bitácora

Diario entre sesiones. El proyecto es multi-sesión: sin esto, cada sesión arranca de cero.

**Este archivo es lo único que se lee al empezar.** Tiene el estado, el mapa del código, el
entorno y el índice. El relato de cada sesión vive en `.claude/bitacora/` y **se lee solo si
algo de acá manda a leerlo**. Si este archivo pasa de ~250 líneas, algo que debía mudarse se
quedó.

---

# ⏭️ ESTADO ACTUAL — leer esto primero

**Última actualización:** 2026-08-13, sesión 15.

```bash
nc -z localhost 5432 && echo arriba || open -a Postgres   # Postgres NO arranca solo
cd web && pnpm test        # 200 en verde        ·        cd web && pnpm dev
# ¿Hay un entrenamiento vivo? El único conteo que da bien: `pgrep -f` y los grep simples
# cuentan de más porque el `bash -c` y el `caffeinate` llevan el comando adentro.
ps -eo command | grep -E '[e]ntrenar\.py' | grep -vcE '^(bash|caffeinate|/bin/zsh)'
```

## 🏃 HAY UNA CORRIDA VIVA — `lora_v4_v2`

**Al 2026-08-13 13:27 iba por el paso 663 de 1642, con 26 canarios verdes y 0 fallidos.**

```bash
tail -3 ia/checkpoints/lora_v4_v2.log      # por qué paso va
grep -c "🐤✗" ia/checkpoints/lora_v4_v2.log   # canarios fallidos: tiene que dar 0
```

Parte de `lora_v4` (flag `--desde`) sobre `train_v5.jsonl`, con las cuatro distribuciones del
generador corregidas. **Se puede cortar en cualquier momento y usar lo que haya**: guarda cada 5
pasos y el dataset está mezclado, así que un corte temprano no deja bancos afuera. Si la máquina
se apagó, se retoma con `--continuar --salida ia/checkpoints/lora_v4_v2` sin perder nada.

⚠️ **El reloj lo decide la memoria, no el dataset:** ~30 s/paso con la Mac libre contra ~110 con
Safari, VS Code, la web y Postgres abiertos. Son 14 h contra 39 h para los mismos pasos.

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

**F9 cerrado.** F10 en curso: `lora_v4` está entrenado y medido (abajo), y `lora_v4_v2` corrige
los sesgos que la medición destapó.

En la base real: **2822 movimientos** · **78 comprobantes** (58 reales + 20 sintéticos) ·
**58 reales revisados a mano** · 9 corridas con su linaje · **37 elecciones humanas** en
`/encontrar`.

**La verdad de referencia son los 58 reales revisados a mano, y es lo más valioso del
proyecto**: sin ella no se mide un solo acierto y rehacerla cuesta horas de una persona. Todo
lo que la escribe (`/revisar`, `lib/revision.ts`) se trata en consecuencia.

Los últimos 7 (`053`–`059`) entraron el 11-ago por el camino IA → `/revisar`, que quedó
aceitado: se dejan en `ia/nuevos/`, `extraer.py` tarda ~15 s por imagen y se corrigen en
pantalla. **Se prefirió sobre la carga manual porque un comprobante tipeado a mano deja la
etiqueta pero no deja ninguna medición.** Detalle en `bitacora/sesion-14-cascada-encontrar.md` §3.

✅ **LA VERDAD ESTÁ REPASADA ENTERA — 58/58.** Tenía errores (9 CUIT de receptor mal, uno con un
CBU en el campo del CUIT) y el usuario los corrigió uno por uno. Al cerrar: **0 CUIT fuera de 11
dígitos, 0 CBU fuera de 22, 0 usos de "Guardar igual"**. Corregirla movió la medición a favor
del LoRA. `bitacora/sesion-12-mayusculas-y-repaso.md`. Se re-chequea en `/revisar`, pestaña
*con dudas* (`motivosDeFormato`): tiene que quedar vacía.

⚠️ **Pendiente de 10 segundos:** el comprobante **126 (`044.jpeg`)** es **el único CUIT de
receptor que no matchea con ningún otro** — parece una transposición, pero puede ser otra cuenta
y estar bien.

**Al comparar se pliegan mayúsculas Y separadores** (decisiones del usuario, 11-ago). Viven en
`normalizarCampo`, **nunca en `paraColumna`**: la base guarda lo que tipeó la persona. El mismo
criterio se aplica al CUIT en la cascada de `/encontrar` (ver más abajo) y al COELSA de
`motor.ts`.

> **El criterio del usuario, textual:** *"quiero que la IA lo escriba como le sea más fácil y
> que luego por código se ponga todo de la misma forma; no le exijamos cosas que podemos
> resolver nosotros de manera muy simple."*

⛔ **`lora_v1` y `lora_v2` están rotos** — causa cerrada: en mlx-vlm `alpha` es la escala
**DIRECTA** (default 0,1), no la de PEFT. Devuelven 0 campos de 256 con la loss bajando igual:
**una métrica de entrenamiento no valida una capacidad que no mide.**
`bitacora/sesion-09-colapso-alpha.md`.

## 🎯 `lora_v4` ES EL MEJOR — 81,7% contra 72,8% de `lora_v3`

842/842 pasos, 21 h, **33 canarios verdes y 0 fallidos**. Medido contra la vara de siempre
(`node --env-file=.env.local comparar-lora.ts`). Detalle en
`bitacora/sesion-15-lora-v4-y-sesgos-del-generador.md` §2.

| Corte | base v1 | `lora_v3_final` | `lora_v4_final` |
|---|---|---|---|
| **Sin `tipo_operacion` NI `moneda`** ← el honesto | 66,1% | 72,8% | **81,7%** |
| Los 6 de la conciliación | 76,0% | 87,5% | **91,7%** |
| Sin Mercado Pago | 53,6% | 67,9% | **80,4%** |
| Solo Mercado Pago | 81,9% | 71,5% | **86,8%** |
| Global (inflado, no usar) | 69,5% | 69,9% | 84,0% |

⛔ **`tipo_operacion` y `moneda` NO son evidencia de nada.** En los 800 sintéticos tienen **un
solo valor** cada uno ("Transferencia" y "ARS"): el modelo los emite siempre, no los lee. Y la
vara resulta ser toda Transferencia en ARS, así que son **32 de 256 campos regalados**. Por eso
el número que se reporta es **81,7%, no 84%**. Mientras la vara sea así, van a dar 100% sin
significar nada.

**El base dejó de ganar en Mercado Pago**, que era el único corte donde `lora_v3` perdía: ya no
hay ningún corte donde convenga el modelo sin entrenar. **`nombre_receptor` se arregló** (1/16 →
9/16) y `cuit_emisor` y `cbu_cvu_emisor` quedaron en 16/16. Empeoraron dos: `concepto` 11→9 y
`banco_emisor` 13→11.

⚠️ **Estos números NO son comparables con nada anterior al 11-ago.** Y `lora_v4` cambió muchas
variables a la vez: la mejora no se puede atribuir a ninguna en particular.

## 🔴 El generador le enseñaba cuatro cosas falsas — corregidas el 13-ago

Al investigar por qué `lora_v4` fallaba sobre un comprobante del usuario apareció la causa raíz.
Todo medido contra los **2822 movimientos del extracto** y los **62 revisados**, no supuesto.
Relato entero en `bitacora/sesion-15-lora-v4-y-sesgos-del-generador.md` §4.

| Sesgo | Estaba | La realidad |
|---|---|---|
| **Montos** | 72% de 6 dígitos (`uniform(500, 350_000)`) | 60% de 5 dígitos, 28% de 4 |
| **Decimales** | 35% terminaba en `,00` | **90%** |
| **Fechas** | 61 fechas, ventana de **2 meses** | — |
| **Nombres** | `fake.name()` mezcla pila y apellido | 49% de 3 palabras, 31% de 5 |

**El sesgo del monto explica el peor error medido:** 28.000 leído como 1.126.081,9. **El de la
fecha explica el otro:** en `044.jpeg` la verdad dice 2023 y el modelo contestó 2026, arrastrando
el año a su ventana de entrenamiento.

⚠️ **La memorización era de la FORMA, no de los valores**: `monto` tenía 787 valores distintos de
800 y los CUIT/CBU todos distintos.

✅ **Decisión del usuario (13-ago): `moneda` y `tipo_operacion` se dejan constantes.** Se le
advirtió que el modelo no puede decir USD ni aunque lo vea. Todo lo que procesa son
transferencias en pesos.

✅ **Los guiones del CUIT se pliegan** (11-ago): `normalizarCampo` compara los 4 campos de
CUIT/CBU solo por sus dígitos. ⛔ `coelsa_id` y `referencia` quedan afuera, son alfanuméricos.
`bitacora/sesion-14-cascada-encontrar.md` §1.

### 🔴 El techo está en la librería

**El LoRA nunca toca la parte visual** (`get_peft_model` recorre solo `model.language_model`):
se entrena *cómo escribir*, no *cómo ver*. Explica el patrón de la medición —mejora en cadenas
numéricas, no en texto que el encoder leyó mal—. El otro techo (la loss cubría toda la
secuencia) **ya está arreglado**. `bitacora/sesion-11-medicion-lora-v3.md` §6.

> ⚠️ **Las curvas de loss NO se comparan con las anteriores al 10-ago.** Con
> `train_on_completions` la CE se suma solo sobre la respuesta pero se divide por toda la
> secuencia: los 5,0 de `lora_v3` y lo que salga ahora miden cosas distintas.

### 🐌 Operación de una corrida larga — ya medido, no volver a medirlo

**La memoria decide el reloj:** 110-136 s/paso con todo abierto contra 24-31 s con la Mac
liberada. Confirmado otra vez el 13-ago: **memoria libre 33% contra 72%, y son 39 h contra 14 h
para los mismos pasos.** ⚠️ **`sysctl vm.swapusage` ENGAÑA** —macOS agranda el swap solo—: el que
sirve es `memory_pressure`.

⛔ **La columna `segundos` de `curva_loss.csv` NO mide lo que tarda un paso.** El cronómetro para
en `loss.item()` (`entrenar.py:370-382`), así que el guardado de 484 MB y el canario quedan
afuera: marcó 24,3 s/paso mientras el reloj real era 89,7. **Para estimar una corrida se usa
`ps -o etime`, nunca la curva.** La nota vieja —*"`--cada 1` está medido que no alarga"*— salía
de esa métrica ciega. En `lora_v4_v2` se usó `--cada 5` a conciencia.

**Cerrar la terminal es seguro** (`PPID=1`), y también cerrar VS Code, la web y Postgres: la
corrida no depende de ninguno. Lo que la mata es **apagar, reiniciar o suspender**. Al reanudar
el canario cuenta los pasos de la corrida en curso y el log va en `>>`, nunca en `>`.

**➡️ LO PRIMERO DE LA PRÓXIMA SESIÓN.**

1. **Ver cómo quedó `lora_v4_v2`** (comandos arriba, en 🏃). Si terminó o se cortó, **medirlo
   igual que a `lora_v4`** — la vara está verificada idéntica, así que los números se comparan
   directo. Los tres comandos están en `bitacora/sesion-15-...md` §2.
2. **Mirar tres imágenes, 5 minutos, y es lo que más despeja:** `005.jpeg` (¿aparece "11300" en
   la pantalla?), `026.jpeg` (¿hay dos fechas?) y `044.jpeg` (¿el año es 2023 o 2026?). Decide si
   los errores son alucinación o campo equivocado. **Claude no puede mirarlas** (regla 2).
3. **Commitear.** `ia/generar.py` y `ia/entrenar.py` tienen cambios sin commitear desde el 13-ago.
4. **Revisar 6 elecciones humanas** en `/encontrar/[id]` — 10 minutos, y deja limpio el número
   de la cascada: `023` (el algoritmo tiene razón, la elección está mal), `007` (CUIT y fecha
   coinciden y el monto no: puede ser un monto mal leído por la IA) y `015`, `032`, `043`,
   `051` (coincidencias de importe a más de 100 días → *deshacer*). Después rehacer la medición.

⚠️ **La vara cambió de etiquetas, no de integrantes.** Los 16 apartados están **FIJOS por
nombre** en `reales.py:APARTADOS` (ya no se sortean), pero al regenerarla con la verdad
repasada **cambiaron 25 de sus 256 campos**. Los números de la tabla 🎯 hay que rehacerlos
contra la vara nueva antes de comparar nada.

```bash
# rehacer el dataset (solo si se agregan comprobantes o se toca generar.py)
ia/.venv/bin/python ia/generar.py --n 1600 --degradados 0.5 --semilla 2026 \
  --salida ia/sinteticos/sinteticos_1600.jsonl
ia/.venv/bin/python ia/reales.py --sinteticos ia/sinteticos/sinteticos_1600.jsonl \
  --salida ia/sinteticos/train_v5.jsonl --test /tmp/vara_check.jsonl
# ⚠️ NUNCA escribir --test sobre test_reales.jsonl: se pisa la vara y se pierde la
#    comparabilidad. Escribir a otro lado y verificar con `diff` que salga idéntica.

# seguir entrenando un adaptador existente sobre datos nuevos (NO es --continuar)
nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py \
  --dataset ia/sinteticos/train_v5.jsonl --desde ia/checkpoints/lora_v4 \
  --lr 5e-5 --alpha 0.1 --rank 16 --canario 25 --cada 5 \
  --salida ia/checkpoints/lora_v4_v2 \
  > ia/checkpoints/lora_v4_v2.log 2>&1 < /dev/null & disown
```

⚠️ **Antes de cualquier corrida: `pmset -g batt | grep "AC Power"`.** A batería la Mac duerme.

⚠️ **Continuar con `--desde` OBLIGA a mantener `rank 16` y `alpha 0.1`** — el adapter tiene que
tener la misma forma. "Más capacidad" y "sumar el encoder visual" **no se pueden hacer
continuando**: piden una corrida desde cero.

### ▶️ Después de esa corrida, por retorno esperado

**Uno por vez y con una sola variable** — así se cerró `alpha`. Ninguno está confirmado.

1. **`lr`**: con la loss dos órdenes más chica, `1e-4` puede quedar corto. Se mira la curva.
2. **`alpha 1.0`**, calibrado en la sesión 10 y nunca usado en una corrida larga.
3. **Más comprobantes reales de bancos nuevos.** Lo que no se fabrica es una foto real.
4. **Leave-one-bank-out**: apartar entidades ENTERAS. Es la única medición que contesta *"¿anda
   con un banco que nunca vio?"*, que es de lo que depende que el sistema valga algo.
5. Por qué se rompió `nombre_receptor` (9/16 → 1/16), y que el checkpoint lo elija la medición
   y no `media_20` — **`mejor/` es red contra la divergencia, NO un selector de calidad.**

## 🔧 Estado de las herramientas de IA

- **Usar `ia/sinteticos/train_v5.jsonl` (1642 = 1600 sintéticos + 42 reales)** — es el único con
  las distribuciones corregidas. `train_v4.jsonl` (842) queda como el de `lora_v4`, intacto.
  Máximo 1.782 tokens por imagen. ⛔ **Nunca `test_reales.jsonl`:** son los 16 de la vara.
- **El dataset sale mezclado**, así que cortar una corrida antes de terminar es válido: los
  primeros 200 ejemplos ya cubren los 10 bancos parejo.
- ⛔ **`train_v3`, `train_v2*` y `train.jsonl` ya NO se pueden usar: sus imágenes se borraron
  por error el 11-ago** y no son reproducibles. Los `.jsonl` quedaron y sirven como evidencia
  de las etiquetas, nada más. Consecuencia que hay que decir si se publica el número: **la
  corrida de `lora_v3` ya no se puede reproducir**; su medición sigue valiendo porque se hizo
  contra la vara, que está intacta. Relato entero en `bitacora/sesion-13-generador.md` §6.
- **El tope de tokens ya no depende de que alguien se acuerde.** Un token cada 28×28 px, **sin
  resize a tamaño fijo: escalan con el ÁREA**. 1.848 es el tope probado; 3.078 y 3.534 mataron
  las corridas del 7 y del 8, **no** SIGHUP. `reales.py` mide y achica una copia a
  `ia/comprobantes_reducidos/`. **La vara va SIEMPRE en tamaño original**: el tope es del
  entrenamiento, no de la inferencia.
- **`generar.py` ya no puede mentir en las etiquetas**: `Lienzo` registra qué se dibujó y `_gt`
  coteja las dos direcciones. Sintéticos **80 por banco, mitad nítidos y mitad degradados**.
- `entrenar.py` guarda **cada paso** y el **estado de Adam** —sin eso reanudar DIVERGE: se
  perdieron 5 h así—. **Canario** (`--canario 25`): cuesta **+3,6%** y detecta en 40 min lo que
  costó 7 h y 9 h.
- `extraer.py`: `parchear_detokenizador()` evita que **una tilde partida mate la corrida
  entera** (bug de `BPEStreamingDetokenizer`, mlx-vlm 0.1.15).

**F7, histórica:** v1 65% · v2 43% · v4 41% sobre 816 campos. **Anteriores al 11-ago: valen
para el orden entre corridas, no como cifras.** `bitacora/sesion-07-medicion.md`.

**Lección de prompting (sesión 3, sigue valiendo):** describir qué SÍ va en un campo, **nunca
qué no** — decirle al modelo qué no poner hace que deje de llenarlo.

## ✅ La cascada de `/encontrar` funciona — 96,7% cuando decide sola (sesión 14)

```
1. nro de transacción + CUIT   → 90%      2. CUIT + monto + fecha → 90%   ← nuevo
3. monto + fecha               → 50%
```

Vive **solo** en `lib/eleccion.ts:candidatos()`, y el **CUIT se compara por sus dígitos**: el
extracto lo trae sin separadores y una persona lo escribe con guiones. Comparar los textos tal
cual dejaba **33 comprobantes sin poder cruzar nunca**. Al 90% pasó de 4 a **26**, y los ambiguos
de 9 a **3**. Medido contra las 37 elecciones humanas: **29 de 30 correctas cuando propone un
solo candidato**. `bitacora/sesion-14-cascada-encontrar.md` §6 y §7.

⛔ **Descartados con medición:** un escalón `CUIT + monto` sin fecha (mete 14 ambiguos) y la
ventana de fecha ±3 días — **los 24 que faltan no son de este Excel** (dato del usuario), así
que forzarles un match es inventar.

## ⚠️ El motor VIEJO no verifica NADA, y tiene 3 agujeros abiertos

`no_verificable 69 · sospechoso 9 · verificado 0`, y **0 CBU propios aprobados**. No es un bug:
`motor.ts` cruza por `cuenta.cbu` y las tres cuentas lo tienen en NULL. **`/encontrar` no lo
usa** — por eso funciona.

Los tres agujeros, en orden: **(1) el motor no mira la moneda** — un comprobante en dólares
puede dar match falso contra un extracto en pesos, el más grave; **(2) `cbu_cvu_receptor` no
alcanza como identificador** — hace falta la cascada CBU → CUIT → nombre, y el CUIT de cada
cuenta en `cuenta`; **(3) los CBU de las 3 cuentas siguen en NULL** desde la sesión 1.

Los tres tocan `motor.ts`, que la re-especificación manda reescribir entero con TDD **con la
cascada de arriba**; ahí `lib/eleccion.ts` y su tabla se borran. **Sin decisión del usuario, no
se toca.**

## Lo que hace falta del usuario

- **Comprobantes reales de fuentes NUEVAS.** No falta cantidad sino variedad: Nación, Brubank,
  BBVA, Uala, Personal Pay, Naranja X, Cuenta DNI, Prex. Cinco de cinco bancos distintos valen
  más que treinta de Mercado Pago, que ya es el 56% de la vara. **El flujo está aceitado:** se
  dejan en `ia/nuevos/` y en ~15 s por imagen quedan precargados en `/revisar`
- **Aprobar sus CBU en `/cbu`.** Hay 6 candidatos esperando. **No los siembra Claude**: que la
  IA haya leído un número 20 veces no lo hace correcto
- **Los CUIT de las 3 cuentas.** El extracto trae CUIT en el 98,7% de los ingresos
- **Un caso real** — extracto y comprobantes de la misma fuente y período. Es lo único que
  valida la regla del 90%. Ya confirmó que va a conseguirlo
- **Decidir la meta del 98%.** Sobre los 16 campos no es alcanzable: el techo lo pone
  `concepto`, texto libre. Propuesta sin responder, **con el número del 11-ago ya plegado**:
  los 6 que deciden la conciliación van **76,0% el base y 87,5% `lora_v3_final`**. Exigir 98%
  **por campo** sobre esos 6 es la métrica correcta
- **Mirar el comprobante 126** (`044.jpeg`): su CUIT de receptor no matchea con ningún otro
- **Resolver la contradicción de `CLAUDE.md`** sobre la regla 2: en la sesión 3 se miraron 3
  comprobantes con autorización expresa y el documento sigue diciendo que los datos nunca salen
  de la máquina. O se actualiza la regla, o se asienta como excepción
- **Decidir sobre los 3 agujeros de diseño**
- **`ia/salida_nuevos.log`**: quedó fuera del `.gitignore` (`*.log` no está cubierto). ¿Se borra
  o se agrega el patrón? Hoy solo tiene progreso, pero un log de extracción puede llevar campos

## ⛔ Lo que no hay que volver a intentar

**Forzarle una fila del extracto a un comprobante que no la tiene.** 24 de los 58 no cruzan y
**no son de este Excel** (dato del usuario, 11-ago): son reales, para entrenar, de otro período.
Una coincidencia de importe a 100 o 1000 días no es la misma transferencia. Ya pasó una vez al
revés —19 cruces por monto+fecha, **0 sobrevivieron al CUIT**—, que es exactamente por qué la
regla mira el CUIT antes que el importe.

**Citar con backticks adentro de un template literal de TS.** Corta el string y el error sale
lejos (`Expected ',', got 'revisado_en'`). Pasó dos veces el 11-ago, las dos en comentarios SQL.

**Borrar archivos en masa sin listar antes qué se borra.** Una limpieza de imágenes huérfanas
comparó rutas relativas contra las absolutas que guardan los `.jsonl`, no coincidió ninguna y
se llevó las 1364. **Si un cotejo de rutas da "0 coincidencias de 1364", eso no es un
resultado: es un síntoma.** Se listan y se confirman antes.

---

# 📚 Índice — leer solo lo que haga falta

| Archivo | Qué tiene | Cuándo leerlo |
|---|---|---|
| `bitacora/reespecificacion.md` | El alcance que pidió la empresa, Looker Studio, la premisa del CUIT en `NRO TRANSACCION` que no se verificó | **Antes de planificar cualquier cosa** |
| `bitacora/sesion-15-lora-v4-y-sesgos-del-generador.md` | **La medición completa de `lora_v4` y por qué el 84% era 81,7%**, los cuatro sesgos del generador con sus números reales (montos invertidos, decimales, ventana de fechas de 2 meses, nombres), los tres errores concretos de monto y fecha, el flag `--desde`, y por qué el cronómetro interno miente | **Antes de tocar `generar.py`, el entrenamiento o la medición** |
| `bitacora/sesion-14-cascada-encontrar.md` | **Por qué el CUIT no cruzaba (guiones) y la cascada de 3 escalones**, la tabla `eleccion` y las dos pantallas de `/encontrar` con su buscador, los 7 comprobantes nuevos, y la medición algoritmo-vs-humano que dejó 6 elecciones para revisar | **Antes de tocar `/encontrar` o `lib/eleccion.ts`** |
| `bitacora/sesion-13-generador.md` | **La auditoría campo por campo de las 10 plantillas y los 2 bugs que tenían**, el `Lienzo` que hace imposible desincronizar etiqueta e imagen, la medición de tokens por resolución, los dos perfiles de calidad, por qué se pasó a 80 por banco, **el borrado accidental de 1364 imágenes con su daño exacto**, y la guarda de tokens de `reales.py` | **Antes de tocar `generar.py`, `reales.py` o el dataset** |
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
web/migraciones/001..008.sql          5 tablas + conciliación + revisado_en +
                                      corrida/extraccion + hoja/fila + cbu_propio +
                                      formato_aceptado_en + eleccion
web/src/lib/db.ts                     el Pool de pg, 4 líneas
web/src/lib/extracto.ts               parser puro: importes, fechas, CUIT, COELSA, huella
web/src/lib/importar.ts               Excel → Postgres. Acepta ruta o Buffer
web/src/lib/importar-comprobantes.ts  JSONL → base. Exporta `normalizarCampo` (compara: pliega
                                      mayúsculas y mira CUIT/CBU SOLO por sus dígitos) y
                                      `paraColumna` (guarda, y NO pliega nada)
web/src/lib/revision.ts               lo que escribe una PERSONA: corregir y cargar a mano.
                                      Además `motivosDeFormato` (CUIT 11 / CBU 22 / "null"),
                                      `cola`+`entra` (los filtros de /revisar) y `proximo`
web/src/lib/eleccion.ts               ⚠️ TEMPORAL. La cascada de 3 escalones (`candidatos`),
                                      el buscador (`buscarMovimientos`) y la elección humana.
                                      Se borra cuando motor.ts la absorba
web/src/lib/motor.ts                  la cascada vieja. Lógica pura, sin base ni red
web/src/lib/conciliacion.ts           puente motor ↔ base + queries del tablero
web/src/lib/fixtures.ts               14 comprobantes con su respuesta conocida
web/src/app/                          las 9 pantallas + acciones.ts (Server Actions)
web/src/app/probar/                   subir foto → 16 campos. Corre ia/extraer.py, sin base
web/comparar-lora.ts                  compara corridas sobre los MISMOS comprobantes, con
                                      cortes por entidad y por campo. Reusa normalizarCampo

ia/extraer.py     inferencia local. Prompts v1/v2/v3, rescata JSON truncado. Con --adaptador
ia/entrenar.py    LoRA sobre mlx-vlm + checkpoint por paso y --continuar
ia/generar.py     dataset sintético. `Lienzo` + `_gt` cotejan etiqueta contra lo dibujado
ia/reales.py      la verdad → JSONL. APARTADOS fijos + guarda de tokens (achica los gigantes)
ia/validar.py     separa lo confiable    ·    ia/calidad.py  compara dos corridas
ia/comprobantes/  los 58 reales   ·   ia/nuevos/  buzón para las tandas que vengan
ia/comprobantes_reducidos/  copias achicadas SOLO para entrenar. El original no se toca

ia/sinteticos/train_v4.jsonl              ⬅️ EL DATASET A USAR (842: 800 sint. + 42 reales)
ia/sinteticos/sinteticos_800.jsonl        los 800 sintéticos solos, 80 por banco
ia/sinteticos/test_reales.jsonl           los 16 apartados con su verdad. NUNCA entrenar
ia/sinteticos/train_v{1,2,3}*.jsonl       ⛔ sin imágenes desde el 11-ago. Solo evidencia
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

**Las 9 pantallas:** `/` tablero con los 6 estados y Recalcular · `/extracto` subir el Excel ·
`/comprobante` carga a mano (⚠️ ver la deuda 🔴) · **`/probar`** subir una foto y ver los 16
campos, sin tocar la base, con selector de adaptador · `/resolver` los ambiguos del motor viejo ·
`/cbu` los CBU propios: un receptor que no esté acá deja al comprobante como *transcripción
dudosa* · `/corridas` · **`/revisar` la corrección humana**, imagen izquierda / 16 campos
derecha, cuatro filtros (pendientes · revisados · **con dudas** · todos), *Revisar N de corrido*,
y al guardar salta al siguiente salvo que algún campo tenga forma imposible: ahí se queda, avisa
cuál y ofrece *Guardar igual* · **`/encontrar` + `/encontrar/[id]`** la asignación comprobante ↔ fila
del extracto: la lista con sus contadores (cuántos resolvió la regla, cuántos elegiste vos y
cuántos de esos la corrigen), y el detalle con la imagen a la izquierda, los candidatos a la
derecha con lo que coincide en verde, y **buscador por detalle / monto / fecha** para las que
la regla no encuentra. Conserva el **export a Excel con colores** (🟢 90% · 🟡 50% · 🔴 sin
encontrar), que es un `<form method="get">` a `/api/exportar`.

⚠️ **Las colas de `/revisar` y `/encontrar` se ordenan SOLO por `id`.** Cualquier orden que
dependa de un timestamp se reordena al guardar y "el que sigue" pasa a ser otro cada vez.

---

# 🔧 Datos del entorno

```bash
# Postgres 18.4 (Postgres.app) — psql NO está en el PATH, por decisión
/Applications/Postgres.app/Contents/Versions/18/bin/psql -d conciliador
DATABASE_URL=postgresql://luisparmigiani@localhost:5432/conciliador   # en web/.env.local

cd web && pnpm dev         # localhost:3000 — SIEMPRE pnpm, nunca npm
cd web && pnpm test        # node --test, sin framework. 200 en verde
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
`psql -v ON_ERROR_STOP=1 -d conciliador -f migraciones/00N_loquesea.sql` con el binario de
arriba, **y también sobre `conciliador_test`** o los tests fallan contra un esquema viejo.

**Dos bases, a propósito.** `conciliador` tiene los **2822 movimientos reales** (2526 ingresos,
296 egresos) + 78 comprobantes; `conciliador_test` es fabricado y descartable, y lo toca solo
`pnpm test`. El `DATABASE_URL` de test está en el script `test` de `package.json`, a la vista:
los tests no llegan a la base real ni por accidente. Ninguna migración lleva `DROP TABLE`.

⚠️ **Un test nuevo NO debe truncar `cuenta`, `movimiento` ni `extracto_carga`.** Corren en serie
(`--test-concurrency=1`) y los archivos posteriores dan por sentado que están sembradas:
vaciarlas los deja sin piso y fallan diez tests que no tienen nada que ver. `eleccion.test.ts`
crea lo suyo con nombres propios y se lo lleva en el `after`.

Node 24.12.0 · pnpm 10.27.0 · Next 16.3.0 · React 19.2.8 · Tailwind 4.3.3 · TS 5.9.3.
**Hay repo git** (rama `main`), al contrario de lo que decía acá hasta la sesión 13. El
`.gitignore` cubre lo sensible — y también `*.jpg`, que es **por qué las imágenes borradas
el 11-ago no se pudieron recuperar**: no estaban versionadas.

**Notas de Next.js 16 que costaron tiempo** (las de `params`/`searchParams` como Promises y
`force-dynamic`, en `bitacora/sesion-02-conciliacion.md`): `PageProps<'/ruta'>` y
`RouteContext<'/ruta'>` **los genera Next** — al crear una ruta nueva `tsc` falla hasta correr
`pnpm exec next typegen` · para devolver un error **sin perder lo tipeado** hace falta
`useActionState`, o sea un componente cliente: un `redirect()` pierde el formulario entero ·
**React no renderiza el `value` de un `<button>`**: para que un dato viaje con el submit hace
falta un `<input type="hidden">`.

---

# 📋 Deudas técnicas conocidas (ninguna bloquea)

| Deuda | Detalle |
|---|---|
| 🔴 **Un comprobante cargado a mano NUNCA llega al entrenamiento** | Cuatro cortes y ninguno avisa: la imagen va a `web/comprobantes/` pero el visor solo mira `ia/comprobantes/` (⇒ **404 en `/revisar`**); `reales.py:56` filtra `corrida_base <> 'sintetico'`, que en SQL da **NULL** cuando la columna es NULL, y un manual la tiene NULL; y `cargarComprobante` no escribe `revisado_en`. Hoy no rompe porque los 78 son `origen='ia'`. **Se decidió NO arreglarlo** (sesión 14): el camino IA → `/revisar` es más rápido para la persona y además deja medición, que la carga manual no deja. Plan en `bitacora/sesion-12-mayusculas-y-repaso.md` §5 |
| **`comparar-lora.ts:71-72` no compila** | `CAMPOS` es readonly y se asigna a un array mutable. **Preexistente**, no rompe la ejecución (Node ignora los tipos), pero ensucia `tsc --noEmit` |
| **La verdad tiene `tipo_operacion` escrito de 3 formas** | `Transferencia` (50), `transferencia_saliente` (11), `Transferencia enviada` (1). El generador ya está alineado; la verdad no. Hasta arreglarlo, ese campo mide tipografía |
| **¿58 o 62 comprobantes revisados?** | La base dice 62 (`revisado_en IS NOT NULL`), la bitácora venía diciendo 58. Hay que saber cuál es el bueno **antes** de reportar cualquier métrica |
| **`generar.py` y `entrenar.py` sin commitear** | Cambios del 13-ago en el working tree. Último commit: `0227240 "lorav4"` |
| **6 elecciones humanas a revisar** | `023`, `007`, `015`, `032`, `043`, `051`. Hasta que se ajusten, la medición de la cascada sale castigada. Ver el punto 2 de la próxima sesión |
| `nombre_receptor` se derrumbó con el LoRA | 9/16 el base contra **1/16** `lora_v3_final`. Sin explicación. Es el único campo donde el LoRA es peor por goleada |
| **`oNulo` no atrapa el string `'null'`** | Trata `''` y `'N/A'` como ausencia, pero el modelo devuelve las tres. Medido sobre los 51: son aciertos contados como errores en **4 (v1) · 4 (v2) · 5 (v3) · 7 (v4)** campos de 816. v1 pasaría de 65,2% a 65,7%. **No cambia el orden ni ninguna conclusión**, por eso no se tocó: arreglarlo mueve todos los números publicados y se decide a propósito. Hay 3 filas de `comprobante` con `'null'`/`'N/A'` guardado como valor. `/probar` ya lo muestra como ausencia |
| `corridas/page.tsx:85` cuenta blobs de JSON, no comprobantes | Latente. Miente el día que haya dos revisados con los 16 campos idénticos |
| Los 20 sintéticos cargados tienen las etiquetas ROTAS | Vienen del generador que inventaba campos. **Hay que recargarlos** desde el dataset nuevo |
| Menores | `@types/node` en `^20` con runtime 24.12 (cast local para `import.meta.main`) · warning `MODULE_TYPELESS_PACKAGE_JSON` · 96 movimientos (3,4%) con `tipo` NULL, a propósito · mojibake en las descripciones, viene del origen y corregirlo sería adivinar |
| **`BITACORA.md` sigue arriba del techo: ~475 contra ~250** | Las sesiones 13 y 14 mudaron a sus archivos las tablas por campo, el relato de los guiones y el de la cascada, y comprimieron el colapso de v1/v2, los techos de la librería, la operación de una corrida larga, los descuentos y la cola de experimentos. **Lo que queda largo es el ESTADO ACTUAL, que es justo lo que hay que leer.** El recorte grande sigue atado a que `lora_v4` cierre F10: ahí se mudan enteras la sección 🎯 y la cola de experimentos, y con `motor.ts` reescrito se va también la de la cascada |
| **Se pueden borrar:** `duplicadas_para_revisar.csv`, `ia/checkpoints/lora_bancos.safetensors` (154 MB) + su `adapter_config.json`, `ia/verdad_referencia.xlsx`, **`ia/checkpoints/smoke_completions/` (462 MB)** | Sobrantes del análisis de duplicadas, del smoke test de F9, de la verdad que reemplazó `/revisar`, y del smoke test de `train_on_completions` del 10-ago — **su log alcanza como evidencia, los pesos de 10 pasos no sirven para nada** |
| **Se conservan como evidencia:** `ia/salida_v2.jsonl` vs `..._rescatado.jsonl`, `ia/sinteticos/train_v1_ROTO.jsonl`, `ia/checkpoints/lora_v1/` | Permiten reproducir el error metodológico, las etiquetas inventadas y la curva de una corrida colapsada |

# ❓ Preguntas de diseño que siguen abiertas

- **La API de deudas (F12)**: qué API es, qué expone, en qué dirección va la información
- **Autoconfirmar la extracción de la IA (F11)** solo se habilita para los campos que F10
  demuestre que lo merecen. Antes no
