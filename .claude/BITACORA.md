# Bitácora

Diario entre sesiones. El proyecto es multi-sesión: sin esto, cada sesión arranca de cero.

**Este archivo es lo único que se lee al empezar.** Tiene el estado, el mapa del código, el
entorno y el índice. El relato de cada sesión vive en `.claude/bitacora/` y **se lee solo si
algo de acá manda a leerlo**. Si este archivo pasa de ~250 líneas, algo que debía mudarse se
quedó.

---

# ⏭️ ESTADO ACTUAL — leer esto primero

**Última actualización:** 2026-08-15, sesión 18.

# 🚦 EL ENTRENAMIENTO SE CERRÓ. AHORA SE CONSTRUYE EL PRODUCTO.

**Hay dos aplicaciones y no se mezclan:**

| Carpeta | Qué es | Stack | Base |
|---|---|---|---|
| `web/` | Con lo que se **entrenó y midió** la IA. **No se toca ni se migra**: es la evidencia | Next.js 16 + TS + `pg` | `conciliador` |
| `portal/` | **El producto.** Portal del cliente ✅ · panel del dueño ✅ | FastAPI + Jinja2 + SQLAlchemy | `portal` |

```bash
nc -z localhost 5432 && echo arriba || open -a Postgres   # Postgres NO arranca solo

# el producto
ia/.venv/bin/uvicorn portal.app:app --reload --port 8000
ia/.venv/bin/python -m portal.verificar_saldos            # el saldo es una columna: chequearlo
ia/.venv/bin/python -m portal.importar <archivo.xlsx> [cuenta]
ia/.venv/bin/python -m portal.lote [--incluir-50]        # ⚠️ carga los CBU propios primero
PORTAL_DATABASE_URL="postgresql+psycopg://luisparmigiani@localhost:5432/portal_test" \
  ia/.venv/bin/python -m unittest discover portal/tests   # 94 en verde

# la herramienta de medición
cd web && pnpm test        # 200 en verde        ·        cd web && pnpm dev
```

## ✅ El producto está entero — cliente y dueño. **94 tests en verde**

El cliente elige su cuenta de una lista (sin contraseña), ve su saldo y su actividad, y sube
comprobantes —foto o **PDF, que se convierte a JPEG solo**—. El dueño sube el extracto
**eligiendo a qué cuenta va**, aprieta un botón, y el lote lee, cruza y acredita.
**El recorrido completo, las diez pantallas y el porqué de cada decisión están en el
`README.md`, sección `# El producto`.** No se repiten acá.

⛔ **`CLAUDE.md` cambió en dos reglas por decisión del usuario:** `portal/` **usa SQLAlchemy**
(el ORM sigue prohibido en `web/`), y **tiene clientes pero NO login** — el id va en la URL y el
único aislamiento real es que cada ruta coteja que el recurso sea de quien lo pide.

### ⚠️ Las cuatro trampas que ya se pisaron. No volver a pisarlas

1. **El saldo es una columna, no una suma.** `registrar_movimiento()` es el único camino que
   lo mueve. **Correr `verificar_saldos.py` después de tocar cualquier cosa que sume o reste**:
   en su primera corrida encontró que los 6 saldos estaban mal.
2. **`sembrar.py --reiniciar` hace `drop_all` y ya borró el comprobante de una persona.**
   Ahora se niega si hay comprobantes subidos. **Los cambios de esquema van con `ALTER TABLE`.**
3. **Un token cada 28×28 px y escalan con el ÁREA.** Agrandar 1,5× son 2,25× de tokens: una
   foto de 4.653 pasó a 10.430 y **mlx pidió 57 GB**. `TOKENS_MAXIMOS = 4000` para las tres
   variantes.
4. **Correr el lote dos veces deja dos series de intentos 1-2-3.** Buscar "la última lectura"
   por `max(intento)` devuelve dos filas y **duplica**; va por `max(id)`. Y el diagnóstico
   mira **solo la última corrida** (`ultimas_lecturas()`), o compara corridas distintas.

**➡️ LO PRIMERO: correr el lote de punta a punta contra la IA.** Nunca terminó bien. Antes hay
que **borrar el CBU `0170099220000012345678`, que es inventado**, y cargar los reales en
`/admin/cbu` — sin ninguno, el lote se niega a arrancar a propósito.
Relato entero, con los tres errores y su diagnóstico, en `bitacora/sesion-18-portal-del-dueno.md`.

---

## ✅ El entrenamiento quedó cerrado — `lora_v4_v2` es el que se usa

**1642/1642 pasos · 17,2 h · 0 canarios fallidos · 82,6% en el corte honesto.** Es el mejor
adaptador, pero le gana a `lora_v4` por **0,9 puntos** y **bajó** en los 6 campos de la
conciliación (91,7% → 90,6%, un solo campo). Relato entero y tabla por campo en
`bitacora/sesion-16-lora-v4-v2-medido-y-looker.md`.

```bash
# ¿hay un entrenamiento vivo? el único conteo que da bien
ps -eo command | grep -E '[e]ntrenar\.py' | grep -vcE '^(bash|caffeinate|/bin/zsh)'
```

⚡ **Antes de lanzar cualquier entrenamiento: `pmset -g batt | grep "AC Power"`.** A batería
la Mac duerme y no hay flag que lo evite: una calibración hizo **9 pasos en 12 horas** por
esto. Y siempre `nohup caffeinate -dims ... < /dev/null & disown`.

⚠️ **Al reanudar con `--continuar` hay que repetir TODOS los hiperparámetros.** Lee el
`estado.json` solo para el contador de pasos y Adam; los flags salen de `argparse`, así que sin
ellos sigue con `--lr 2e-5` y `--dataset train.jsonl` **en silencio**. Comando exacto en el
README.

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
F6 ✅  F7 ✅  F8 ✅  F9 ✅  F10 ✅           BLOQUE B — la IA (cerrado el 15-ago)
PORTAL: cliente ✅   dueño ✅               BLOQUE C — el producto
```

**F10 cerrado:** cinco adaptadores entrenados, cuatro medidos contra la misma vara, y el mejor
(`lora_v4_v2`, 82,6%) le saca 16,5 puntos al modelo base. **Es el que usa el producto, fijo.**
La cola de experimentos sigue viva en `sesion-16` §8, pero ya no bloquea nada.

En la base real: **2822 movimientos** · **78 comprobantes** (58 reales + 20 sintéticos) ·
**58 reales revisados a mano** · 10 corridas con su linaje · **37 elecciones humanas** en
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

## 🎯 EL MEJOR ES `lora_v4_v2` — 82,6% contra 66,1% del modelo base

| Corte | base v1 | `lora_v3` | `lora_v4` | `lora_v4_v2` |
|---|---|---|---|---|
| **Sin `tipo_operacion` NI `moneda`** ← el honesto | 66,1% | 72,8% | 81,7% | **82,6%** |
| **Los 6 de la conciliación** | 76,0% | 87,5% | **91,7%** | 90,6% |
| Sin Mercado Pago | 53,6% | 67,9% | **80,4%** | **80,4%** |
| Solo Mercado Pago | 81,9% | 71,5% | 86,8% | **88,2%** |
| Global (inflado, no usar) | 69,5% | 69,9% | 84,0% | 84,8% |

Las tablas por campo y por entidad, y el detalle de cada corrida, están en
`bitacora/sesion-16-...md` §3 y `sesion-15-...md` §2.

⛔ **`tipo_operacion` y `moneda` NO son evidencia de nada.** En los sintéticos tienen **un solo
valor** cada uno ("Transferencia" y "ARS"): el modelo los emite siempre, no los lee. Y la vara
resulta ser toda Transferencia en ARS, así que son **32 de 256 campos regalados**. Por eso se
reporta el corte sin ellos. Mientras la vara sea así, van a dar 100% sin significar nada.

🔴 **Lo que la última medición dejó claro: los cuatro sesgos corregidos NO movieron `monto` ni
`fecha`** (14/16 los dos, idénticos a `lora_v4`). La corrección era correcta —medida contra los
2822 movimientos— pero no se tradujo en aciertos. **O la vara de 16 es demasiado chica, o esos
2 fallan por lectura visual, que es donde el LoRA no llega.** No se puede separar con lo que hay:
hacen falta más comprobantes reales.

⚠️ **Estos números NO son comparables con nada anterior al 11-ago.** Y tanto `lora_v4` como
`lora_v4_v2` cambiaron varias variables a la vez: la mejora no se atribuye a ninguna.

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

**Pendientes del entrenamiento. Ya NO bloquean nada** — el producto avanza sin ellos.

1. **Commitear.** Arrastra desde la sesión 16 y **lo hace el usuario**: el `README.md` reescrito,
   `metricas/`, `ia/metricas.sh`, `web/comparar-lora.ts`, `.gitignore`, **todo `portal/`**,
   `CLAUDE.md` y esta bitácora.
2. **Mirar tres imágenes, 5 minutos, y es lo que más despeja:** `005.jpeg` (¿aparece "11300" en
   la pantalla?), `026.jpeg` (¿hay dos fechas?) y `044.jpeg` (¿el año es 2023 o 2026?). Decide si
   los errores son alucinación o campo equivocado. **Claude no puede mirarlas** (regla 2).
3. **Revisar 6 elecciones humanas** en `/encontrar/[id]` — 10 minutos, y deja limpio el número
   de la cascada: `023` (el algoritmo tiene razón, la elección está mal), `007` (CUIT y fecha
   coinciden y el monto no: puede ser un monto mal leído por la IA) y `015`, `032`, `043`,
   `051` (coincidencias de importe a más de 100 días → *deshacer*). Después rehacer la medición.
4. **Armar el tablero de Looker Studio** con los tres CSV de `metricas/` — ver
   `metricas/LEEME.md`, que tiene el gráfico de cada página. Los archivos ya están generados.

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
```

**Los comandos de entrenar (`--desde`), de reanudar (`--continuar`) y de medir están en el
`README.md`**, sección *El entrenamiento*, con sus advertencias al lado. No se copian acá para
no tener dos versiones que se despeguen.

⚠️ **Antes de cualquier corrida: `pmset -g batt | grep "AC Power"`.** A batería la Mac duerme.

⚠️ **Continuar con `--desde` OBLIGA a mantener `rank 16` y `alpha 0.1`** — el adapter tiene que
tener la misma forma. "Más capacidad" y "sumar el encoder visual" **no se pueden hacer
continuando**: piden una corrida desde cero.

### ▶️ La cola de experimentos se mudó a `bitacora/sesion-16-...md` §8

**Uno por vez y con una sola variable** — así se cerró `alpha`. Ninguno confirmado. El primero
de la lista es **más comprobantes reales de bancos nuevos**: es lo único que no se fabrica, y lo
que destraba la pregunta que la medición dejó abierta.

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
- **Aprobar sus CBU en `/cbu`.** De 8 candidatos distintos, 5 ya están aprobados y **quedan 3**
  (verificado el 15-ago). **No los siembra Claude**: que la IA haya leído un número 20 veces no
  lo hace correcto
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
| `bitacora/sesion-18-portal-del-dueno.md` | **Los tres errores de esta sesión con su diagnóstico**: el `--reiniciar` que borró un comprobante de una persona, el lote que se cayó en silencio (tokens × área → 57 GB) y los comprobantes duplicados por `max(intento)` · la verificación del porteo del parser contra los 2822 reales · **la `huella()` de `web/` que no reproduce su propia fórmula** · las 12 decisiones del usuario | **Antes de tocar `portal/lote.py`, el importador o las pantallas del dueño** |
| `bitacora/sesion-17-portal-cliente.md` | **La especificación completa del portal del dueño dictada por el usuario** (el lote, la relectura ×3, los cuatro desenlaces, el CBU propio) y las 3 decisiones a tomar antes de escribirlo · las 6 decisiones de diseño del portal del cliente con lo que se descartó · **el bug de los saldos que encontró el verificador** y por qué `registrar_movimiento()` lleva dos `flush()` | **Antes de tocar `portal/` — y SIEMPRE antes de empezar el portal del dueño** |
| `bitacora/sesion-16-lora-v4-v2-medido-y-looker.md` | **La medición completa de `lora_v4_v2` con su tabla por campo**, por qué los sesgos corregidos no movieron `monto` ni `fecha`, el reloj real de la reanudación (y por qué la memoria NO lo explicó esta vez), los tres CSV de Looker Studio con el porqué del formato largo, los conteos verificados contra la base, y la cola de experimentos | **Antes de tocar el entrenamiento, la medición o el tablero** |
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

## `portal/` — el producto (base `portal`, SQLAlchemy 2.0)

```
portal/db.py                engine + Sesion. 13 líneas, sin capa de nada
portal/modelos.py           Cliente · Comprobante · MovimientoCuenta, los 4 estados como
                            constantes, y `registrar_movimiento()` — el ÚNICO camino que
                            mueve el saldo. Sus dos flush() están explicados adentro
portal/archivos.py          valida el upload, PDF→JPEG con `pdftoppm`, y el nombre del
                            archivo lo pone el SERVIDOR (uuid), nunca el cliente
portal/app.py               las 5 rutas + los filtros `pesos` y `dia` de Jinja
portal/sembrar.py           6 clientes inventados, semilla 2026. `--reiniciar` rehace todo
portal/verificar_saldos.py  recalcula el libro y sale con 1 si algún saldo se despegó
portal/extracto.py          el parser del banco. Porteo de extracto.ts, 33 tests portados
portal/importar.py          Excel → base. Cuenta elegible + registro de cargas (deshacibles)
portal/cascada.py           los 3 escalones del cruce. Lógica pura, sin base y sin IA
portal/lote.py              el lote: 3 variantes de imagen, los desenlaces, y `diagnostico()`
portal/exportar.py          el extracto conciliado a Excel, con colores por certeza
portal/admin.py             las pantallas del dueño
portal/comprobantes/        lo que sube la gente. En .gitignore: son datos reales
portal/tests/               6 tests con `unittest`. Se NIEGAN a correr si la URL no
                            termina en `portal_test`
```

**Las tablas del producto:** `cliente` · `comprobante` · `movimiento_cuenta` ·
`movimiento_banco` (su `comprobante_id` es **UNIQUE**: la fila tomada la garantiza Postgres) ·
`carga_extracto` · `cbu_propio` · `extraccion` · `correccion`.

**Las 3 rutas con filo:** `POST /cliente/{id}/subir` guarda **el archivo primero y la fila
después** · `GET /cliente/{id}/comprobante/{cid}` **coteja que el comprobante sea de ese
cliente** —es el único aislamiento que hay, no hay login— · `/` es el selector de cuenta.

## `web/` — la herramienta con la que se midió (base `conciliador`, `pg` plano)

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

ia/metricas.sh    junta las curvas de loss de todas las corridas en un CSV
metricas/         los 3 CSV del tablero de Looker Studio + LEEME.md con las 3 páginas.
                  `*.csv` está en .gitignore: metricas/ es la ÚNICA excepción

ia/sinteticos/train_v5.jsonl              ⬅️ EL DATASET A USAR (1642: 1600 sint. + 42 reales)
ia/sinteticos/train_v4.jsonl              el de lora_v4 (842). Intacto, para reproducirlo
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
| ✅ ~~**¿58 o 62 comprobantes revisados?**~~ | **RESUELTO (15-ago): los dos.** `revisado_en IS NOT NULL` da 62 (incluye 4 sintéticos); con `AND corrida_base <> 'sintetico'` da 58, los reales — que es el filtro de `reales.py` y **el número a reportar** |
| **Sin commitear** | Lo de la sesión 16 (`README.md`, `metricas/`, `ia/metricas.sh`, `web/comparar-lora.ts`) **más todo lo de la 17**: `portal/` entero, `.claude/CLAUDE.md`, `.claude/BITACORA.md`, `.claude/bitacora/sesion-1{6,7}-*.md`, `.gitignore` |
| 🔴 **El lote nunca corrió entero contra la IA** | Los 21 tests usan un doble que devuelve campos fijos: prueban la lógica, no que el modelo lea bien ni cuánto tarda. La primera corrida real murió por los tokens (ya arreglado) y **no se volvió a probar** |
| **Falta el exportador de `correccion` a JSONL** | La tabla guarda `campo · valor_leido · valor_correcto`, que es lo que necesita `ia/reales.py`, pero el script que las convierte no existe. Sin él la fábrica de datos no cierra el círculo |
| ⛔ **La `huella()` de `web/` no reproduce su fórmula** | Con los mismos 5 campos, `shasum`, Node inline y Python dan `651b8a98…` y `extracto.ts` da `ccfa65ee…`. Sin explicación. No bloquea —cada base es consistente consigo misma— pero **las huellas de las dos bases no son comparables** |
| **Un CBU inventado en la base real** | `0170099220000012345678` en `/admin/cbu` lo cargó Claude para probar. **Borrarlo** y cargar los reales |
| **`portal/` no tiene migraciones** | Las tablas se crean con `create_all()` sobre base vacía; un cambio de esquema se resuelve con `sembrar.py --reiniciar`. Alcanza **solo mientras los datos sean inventados**. El día que haya un dato real de un cliente, hace falta Alembic |
| **2 comprobantes de prueba en la base `portal`** | En la cuenta de Aníbal Ferreyra (id 2), fabricados con Pillow durante la verificación. Se van con `python -m portal.sembrar --reiniciar` |
| **`*.err` no está en `.gitignore`** | `ia/salida_lora_v4_v2_final.err` quedó sin trackear pero visible. Hoy solo lleva progreso y warnings, igual que `ia/salida_nuevos.log`. Misma decisión pendiente: ¿se borran o se agregan los patrones `*.err` y `*.log`? |
| **6 elecciones humanas a revisar** | `023`, `007`, `015`, `032`, `043`, `051`. Hasta que se ajusten, la medición de la cascada sale castigada. Ver el punto 2 de la próxima sesión |
| `nombre_receptor` se derrumbó con el LoRA | 9/16 el base contra **1/16** `lora_v3_final`. Sin explicación. Es el único campo donde el LoRA es peor por goleada |
| **`oNulo` no atrapa el string `'null'`** | Trata `''` y `'N/A'` como ausencia, pero el modelo devuelve las tres. Medido sobre los 51: son aciertos contados como errores en **4 (v1) · 4 (v2) · 5 (v3) · 7 (v4)** campos de 816. v1 pasaría de 65,2% a 65,7%. **No cambia el orden ni ninguna conclusión**, por eso no se tocó: arreglarlo mueve todos los números publicados y se decide a propósito. Hay 3 filas de `comprobante` con `'null'`/`'N/A'` guardado como valor. `/probar` ya lo muestra como ausencia |
| `corridas/page.tsx:85` cuenta blobs de JSON, no comprobantes | Latente. Miente el día que haya dos revisados con los 16 campos idénticos |
| Los 20 sintéticos cargados tienen las etiquetas ROTAS | Vienen del generador que inventaba campos. **Hay que recargarlos** desde el dataset nuevo |
| Menores | `@types/node` en `^20` con runtime 24.12 (cast local para `import.meta.main`) · warning `MODULE_TYPELESS_PACKAGE_JSON` · 96 movimientos (3,4%) con `tipo` NULL, a propósito · mojibake en las descripciones, viene del origen y corregirlo sería adivinar |
| 🔴 **`BITACORA.md` empeoró: 580 líneas contra un techo de ~250** | La sesión 17 sumó el producto sin sacar nada. **Ahora sí se puede recortar de verdad, porque F10 cerró:** todo lo del entrenamiento —la tabla 🎯 de adaptadores, los cuatro sesgos del generador, la operación de una corrida larga, el techo de la librería, las herramientas de IA— pasó de "hay que leerlo para trabajar" a historia, y su lugar es `sesion-15` y `sesion-16`, que ya lo cuentan entero. Arriba alcanza con: **`lora_v4_v2` es el adaptador, 82,6%, y el detalle está en la sesión 16.** La sección de la cascada de `/encontrar` se va cuando el portal del dueño tenga la suya |
| **Se pueden borrar:** `duplicadas_para_revisar.csv`, `ia/checkpoints/lora_bancos.safetensors` (154 MB) + su `adapter_config.json`, `ia/verdad_referencia.xlsx`, **`ia/checkpoints/smoke_completions/` (462 MB)** | Sobrantes del análisis de duplicadas, del smoke test de F9, de la verdad que reemplazó `/revisar`, y del smoke test de `train_on_completions` del 10-ago — **su log alcanza como evidencia, los pesos de 10 pasos no sirven para nada** |
| **Se conservan como evidencia:** `ia/salida_v2.jsonl` vs `..._rescatado.jsonl`, `ia/sinteticos/train_v1_ROTO.jsonl`, `ia/checkpoints/lora_v1/` | Permiten reproducir el error metodológico, las etiquetas inventadas y la curva de una corrida colapsada |

# ❓ Preguntas de diseño que siguen abiertas

- **La API de deudas (F12)**: qué API es, qué expone, en qué dirección va la información
- **Autoconfirmar la extracción de la IA (F11)** solo se habilita para los campos que F10
  demuestre que lo merecen. Antes no
