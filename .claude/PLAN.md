# Plan de ejecución

> **Este archivo dice qué hay que hacer, no qué está hecho.** El estado va en `BITACORA.md`,
> en el bloque **ESTADO ACTUAL** de arriba de todo. Si los dos se contradicen, gana la
> bitácora: es lo que se verificó contra los datos.
>
> Al 2026-08-06: **Bloque A terminado** (F0 a F5), Bloque B sin empezar.

Trece fases en tres bloques. Cada fase tiene un **criterio de listo verificable con un
comando**, no con una opinión. No se empieza la siguiente sin cumplir el anterior.

```
BLOQUE A — Conciliación (el producto)          F0 → F5
BLOQUE B — IA (requisito de la materia)        F6 → F10
BLOQUE C — Integración                         F11 → F12
```

**Por qué este orden.** La conciliación es el producto; la IA solo evita tipear 16 campos a
mano. Al terminar el Bloque A el sistema ya sirve cargando comprobantes manualmente. Si la IA
después falla —y el intento anterior falló— lo que se pierde es comodidad, no el proyecto.
Al revés, arrancar por la IA deja semanas de trabajo sin nada que use esos datos.

---

# BLOQUE A — Conciliación

## F0 · Preparar el terreno

**Objetivo:** que todo arranque, sin lógica todavía.

1. `git init` y `.gitignore` que excluya **antes del primer commit**:
   `TRANSFERENCIAS.xlsx`, `*.xlsx`, `viejo./comprobantesReales/`, `comprobantes/`,
   `checkpoints/`, `env/`, `node_modules/`, `.env`
2. PostgreSQL local (Postgres.app o `brew install postgresql@17`), base `conciliador`
3. Next.js con TypeScript en `web/`, más `pg` y `exceljs`. Nada más. **Siempre con `pnpm`.**
   Va en subcarpeta porque `create-next-app` pisa el `README.md` y el `.gitignore` de la raíz.
4. Renombrar `viejo.` → `viejo` (el punto final del nombre rompe rutas)

**Listo cuando:** ningún archivo de datos reales queda fuera del `.gitignore`,
`psql -d conciliador -c '\dt'` conecta, y `pnpm dev` levanta.

**Riesgo:** commitear datos bancarios reales. Es irreversible en la práctica. El `.gitignore`
va primero que el `git init`.

---

## F1 · Esquema de base de datos

**Objetivo:** las tablas, pensadas para los seis estados y para tres cuentas.

```sql
cuenta            id, nombre, banco, cbu, alias, activa
                  -- SUCESION, QUIQUE, MARIELA. Diseñado para N desde el día uno.

extracto_carga    id, cuenta_id, archivo, hash_archivo, subido_en,
                  filas_leidas, filas_nuevas, filas_duplicadas, fecha_min, fecha_max
                  -- fecha_min/max definen la COBERTURA: sin esto no se puede
                  --   distinguir "sospechoso" de "no verificable"

movimiento        id, cuenta_id, carga_id, fecha, nro_transaccion, descripcion,
                  importe NUMERIC(14,2), es_ingreso, requiere_revision,
                  cuit_emisor, coelsa_id, tipo, huella UNIQUE
                  -- SALDO no se guarda: es información del banco, no del proyecto
                  -- huella = hash(cuenta, fecha, nro, importe, descripcion) → dedup

comprobante       id, archivo, hash_imagen UNIQUE, subido_en, origen, estado_extraccion,
                  + los 16 campos extraídos
                  -- hash_imagen detecta el reenvío de la misma imagen al instante

conciliacion      id, comprobante_id, movimiento_id NULL, estado, confianza, regla,
                  decidido_por, decidido_en, nota
                  -- UNIQUE(movimiento_id) WHERE movimiento_id IS NOT NULL
                  --   → un movimiento no puede ser reclamado por dos comprobantes
```

**Decisiones cerradas:**

- `NUMERIC(14,2)`, nunca `float`. Es plata.
- `huella` como UNIQUE en la base, no como chequeo en el código. `NRO TRANSACCION` no sirve
  de clave: hay 1309 presentes y solo 1286 distintos.
- El `UNIQUE` parcial sobre `movimiento_id` es lo que hace imposible el doble cobro. La base
  lo garantiza; no depende de que el código se acuerde.

**Listo cuando:** las migraciones corren desde cero sobre una base vacía, y un test confirma
que insertar dos conciliaciones sobre el mismo `movimiento_id` explota.

---

## F2 · Importador de extracto  ← la fase más traicionera

**Objetivo:** Excel → Postgres, sin duplicar, sin un solo importe mal leído.

Es la fase donde un error no se nota: no rompe nada, solo produce un número equivocado que
después acusa a un cliente honesto.

### 2.1 El SALDO se descarta

Es el saldo de la cuenta al momento del movimiento: información del banco, no del proyecto.
No se guarda, no se modela, no se muestra.

### 2.2 Parseo de importes con dos formatos mezclados

Formato argentino (`$ 368.500,00`) y estadounidense (`$ 16,000.00`) mezclados en la misma
columna, que además está guardada **como texto** en las 2843 filas.

```
1. Sacar '$' y espacios. Guardar el signo (negativo = egreso).
2. Tiene '.' y ',' → el último de los dos es el decimal.       $ 368.500,00 → 368500.00
                                                               $ 16,000.00  →  16000.00
   → resuelve 2813 de las 2841 filas con separador. Sin ambigüedad posible.
3. Tiene un solo separador:
     1-2 dígitos después → decimal                             $ 1.50       →     1.50
     3 dígitos después   → AMBIGUO ($ 1.500 = 1500 o 1.50?)     → paso 4
4. Ambiguo: la fila queda `requiere_revision` y se muestra en el
   resumen de importación. NO SE ADIVINA.
```

El paso 4 es obligatorio aunque en este archivo casi no se use: un importe inventado es una
acusación falsa, y el costo de mirar a mano lo que el parser no resolvió es de minutos.

**Medido contra el archivo el 2026-08-06 — el "29 ambiguas" era falso.** Las 29 filas con un
solo separador tienen **todas 2 dígitos detrás** (`$ 16,00`): son decimales, sin duda posible.
Ninguna tiene 3 dígitos detrás, que es el único caso irresoluble.

La ambigüedad real del archivo es **1 fila**, y no es de formato numérico: la celda dice
literalmente `############`. Como toda la columna está guardada como texto, ese `###` **es** el
dato — el importe no existe en el archivo. Queda `requiere_revision`, que es lo que el
`CHECK (importe IS NOT NULL OR requiere_revision)` de F1 obliga.

### 2.3 Extracción desde la descripción

```
Fecha       exceljs devuelve Date a medianoche UTC — NO seriales. Se lee en UTC
CUIT        (?<!\d)(20|23|24|27|30|33|34)\d{9}(?!\d)   → 90-93% de las filas
COELSA      TRANSF:|CREDIN: + [A-Z0-9]{20,24}          → 84 filas (3,0%)
Tipo        prefijo: ING TRANSF, TRANSF, TEF, CCERR, CREDIN, DEBIN,
            IMP., IIBB, AFIP, AGUAS, EPE, MOVISTAR, TASAS, MUN, CAPITALIZACION
```

**Medido contra el archivo el 2026-08-06:**

- **COELSA son 84, no 95.** Hay 1268 filas con `TRANSF:` o `CREDIN:`, pero solo 84 traen un
  token de 22 caracteres; el resto son textos cortos que no son un ID. Todos los COELSA reales
  miden **exactamente 22**. El patrón queda en `{20,24}` por si otro banco usa otro largo.
- **96 filas (3,4%) no matchean ningún prefijo** y quedan con `tipo` NULL. Son categorías que
  faltan en la lista (`COMPENSACION` 11, `EGRESO` 8, `DEBITO` 6, `CLARO` 5, `LEY` 5,
  `ACREDITACION` 5, y una cola larga). **Se dejan en NULL a propósito:** la cascada de F4 cruza
  por COELSA, CUIT, importe y fecha, nunca por `tipo`. Perseguir la cola larga no compra nada.
- **El archivo trae mojibake** (`COMPENSACIàN` por `COMPENSACIÓN`). Es de la codificación del
  origen. No se corrige: sería adivinar, y las descripciones no se usan para cruzar.

Los egresos (importe negativo, servicios, impuestos) se guardan pero se excluyen de la
conciliación: son 300 filas. Los nombres se ignoran: vienen truncados a 8-16 caracteres.

### 2.4 Deduplicación

Una hoja por cuenta. `huella` UNIQUE, `INSERT ... ON CONFLICT DO NOTHING`. Al terminar, el
resumen dice cuántas entraron y cuántas ya estaban. Esto resuelve el problema de descargar
extractos con períodos superpuestos: se puede subir el mismo archivo dos veces sin consecuencia.

Las 21 filas repetidas del archivo actual **se descartan solas, no se marcan para revisión.**
Se verificó una por una que son pegado duplicado y no transferencias reales: los dos miembros
de cada par comparten el saldo y el importe no es cero, así que el saldo se movió una sola
vez. En `SUCESION` las filas 100-107 son un espejo perfecto — una tanda pegada dos veces, la
segunda en orden invertido. El detalle está en `BITACORA.md`.

**Listo cuando:**
- Se leen **2843** filas con contenido (SUCESION 1309 · QUIQUE 1315 · MARIELA 219) y quedan
  **2822** movimientos: 21 descartados por duplicados
- Las **518** filas vacías se saltean sin entrar al resumen
- Cero importes adivinados: la **1** fila ambigua (la celda `############`) quedó marcada
  `requiere_revision` y listada
- Reimportar el mismo archivo inserta **0** filas nuevas
- Los **84** COELSA se extrajeron, y los CUIT en el 90-93% de las filas
- `fecha_min`/`fecha_max` por cuenta quedan registrados

> El "3364" de la primera versión de este plan era incorrecto: sumaba las 518 filas vacías y
> las 3 filas de encabezado. Verificado el 2026-08-06 contra el archivo. Detalle en
> `BITACORA.md`. `README.md` quedó corregido el mismo día.

---

## F3 · Generador de datos de prueba

> **Se hizo en dos pasos, distinto de lo que dice abajo.** F4 es lógica pura: no necesita
> imágenes ni un Excel, necesita datos. Así que 3.1 quedó como un módulo TS
> (`web/src/lib/fixtures.ts`) que F4 importa directo, y 3.2 como un `.xlsx` chico generado
> **dentro del test** del importador. Las imágenes de comprobantes son del Bloque B (F8).
> El detalle, en `BITACORA.md`.

**Objetivo:** fixtures donde la respuesta correcta se conoce de antemano.

Los 52 comprobantes reales son de otra fuente y otro período: **no cruzan con este extracto.**
Sirven para medir la IA (Bloque B), no para probar la conciliación. Así que el motor se prueba
con datos fabricados a propósito.

El generador produce un **par coherente** —comprobantes + un extracto que los contiene— con los
seis estados representados a voluntad:

| Se fabrica | Para probar |
|---|---|
| Comprobante + su movimiento, con COELSA | Regla 1 |
| Comprobante + su movimiento, sin COELSA | Regla 2 (CUIT + importe + fecha) |
| Comprobante con fecha un día antes que el movimiento | Tolerancia ±1 día hábil |
| Comprobante sin movimiento, cuenta cubierta | **Sospechoso** |
| Comprobante a una cuenta no cargada | **No verificable** |
| Comprobante fuera del rango del extracto | **No verificable** |
| Dos comprobantes, un solo movimiento | **Duplicado** |
| Dos movimientos, mismo importe y fecha | **Ambiguo** |
| Movimiento sin comprobante | **Sin comprobante** |
| Importes en formato AR y US mezclados | El parser de F2 |
| Fila repetida | El dedup de F2 |

**Listo cuando:** un comando genera el par, y cada caso trae escrito cuál es su estado
esperado. Sin esto, F4 no tiene contra qué testear.

---

## F4 · Motor de conciliación  ← el corazón

**Objetivo:** la cascada del README, con TDD estricto.

Lógica pura: entra un comprobante y el conjunto de movimientos, sale un estado. Sin base de
datos, sin red, sin archivos. Testeable al 100%.

```
1. COELSA idéntico
   └─► verificado, confianza alta

2. CUIT emisor + importe exacto + fecha ±1 día hábil
   └─► verificado, confianza alta

3. Importe exacto + fecha ±1 día hábil, sin CUIT
   ├─ un candidato    ─► verificado, confianza media
   └─ varios          ─► ambiguo

4. Sin candidatos
   ├─ ¿cuenta cargada Y fecha dentro de [fecha_min, fecha_max]?
   │   ├─ sí ─► sospechoso
   │   └─ no ─► no verificable

5. ¿El movimiento ya fue reclamado?  ─► duplicado, los dos comprobantes
6. Movimientos ingresantes sin comprobante ─► sin comprobante
```

**Reglas duras:**

- El paso 4 es la salvaguarda contra acusar a un cliente honesto. Sin cobertura no hay veredicto.
- Un movimiento, un comprobante. Lo garantiza el `UNIQUE` de F1.
- Los ambiguos **no se resuelven solos.** Se listan para que decida una persona.
- La tolerancia ±1 día hábil es configurable: una transferencia de las 21:46 impacta al día
  siguiente, y un fin de semana corre al lunes.

**Listo cuando:** todos los casos de F3 dan el estado esperado, incluidos los negativos. Los
tests se escribieron antes que la implementación.

---

## F5 · Interfaz

**Objetivo:** el sistema usable, cargando comprobantes a mano. **Este es el hito que importa.**

Cuatro pantallas. No cinco.

1. **Subir extracto** — elegir cuenta, subir Excel, ver el resumen (nuevas / duplicadas / a revisar)
2. **Cargar comprobante** — subir imagen, completar los 16 campos a mano, guardar
3. **Tablero** — la lista con los seis estados, filtro por estado / cuenta / fecha
4. **Resolver** — los ambiguos, con los candidatos al lado, y un botón por candidato

Sin login, sin dashboard de métricas, sin gráficos, sin animaciones.

**Listo cuando:** se puede subir el extracto real, cargar un comprobante a mano, y el tablero
muestra su estado. **A partir de acá el sistema ya sirve, sin una línea de IA.**

> Hecho el 2026-08-06. Falta **un solo dato** para que muestre un `verificado`: los **CBU de
> las 3 cuentas**, que están en `NULL`. Sin eso el motor no sabe a qué cuenta apunta un
> comprobante y devuelve `no_verificable` — que es lo correcto, pero deja el tablero mudo.

---

# BLOQUE B — IA

## F6 · Verdad de referencia

**Objetivo:** 30 comprobantes reales con sus 16 campos confirmados por una persona.

Sin esto no hay forma de medir nada, y sin medición el fine-tuning no se puede defender ante
la cátedra: no se podría demostrar que mejoró algo.

**Método de corrección, no de tipeo:** correr el modelo base sobre los 52, volcar los campos a
una planilla, y **corregir solamente lo que está mal.** De tipear 832 campos a revisar unos
100. De ~4 horas a ~45 minutos.

Con 30 bien etiquetados alcanza para una medición defendible; no hacen falta los 52.

**Regla que no se negocia:** cada campo lo confirma una persona. Aceptar la salida del modelo
sin mirarla convierte la medición en un modelo evaluándose a sí mismo, y el número deja de
significar nada.

**Listo cuando:** existe `verdad_referencia.jsonl` con 30 comprobantes, revisados uno por uno,
y esos 30 quedan **excluidos de todo entrenamiento** para siempre.

---

## F7 · Baseline zero-shot

**Objetivo:** cuánto acierta el modelo base, sin entrenar. Es el grupo de control.

Correr Qwen2-VL-7B-4bit sobre los 30 de F6. Medir **campo por campo**, no "el comprobante
entero bien o mal": lo que importa es cuáles campos fallan.

Los cuatro campos críticos para la conciliación son `monto`, `fecha`, `cuit_emisor` y
`coelsa_id`. Que falle `concepto` no cambia nada; que falle `monto` rompe todo.

Evaluar también `Qwen2.5-VL-7B` si `mlx-vlm` lo soporta — el modelo actual es de 2024. Vía
context7 / huggingface-skills, descarga local únicamente.

**Listo cuando:** hay una tabla de accuracy por campo, con N declarado, guardada para comparar
en F10.

---

## F8 · Dataset sintético

**Objetivo:** ejemplos de entrenamiento con etiquetas gratis.

Se generan comprobantes en HTML, se renderizan a imagen, y la verdad de referencia sale de los
datos con que se generaron. Cero etiquetado manual — para eso existen.

Base: `viejo/generar_sinteticos.py` ya tiene 10 plantillas (MP, Macro, Santander, Galicia, BBVA,
Nación, Naranja X, Brubank, Ualá, Personal Pay) y `train.jsonl` tiene 300 ejemplos. Se reusa,
no se reescribe.

Cambios necesarios:
- Migrar de dibujo con PIL a HTML + render: más fácil de mantener y más parecido a un
  comprobante real
- Ruido de WhatsApp: recompresión, rotación leve, desenfoque, recorte, escala
- **Arreglar el formato del JSONL.** `image/prompt/answer` no es lo que espera `mlx_vlm.lora`
  0.1.15, que quiere `messages`/`images`. **Este es el bug que mató el intento anterior.**
  Se verifica contra la documentación real de la versión instalada, vía context7, antes de
  generar los 300 ejemplos de nuevo.

**Listo cuando:** el dataset valida contra el formato que la versión instalada de `mlx-vlm`
realmente acepta —confirmado leyendo su código o su documentación, no suponiéndolo— y ninguno
de los 30 de F6 está adentro.

---

## F9 · Fine-tuning LoRA

**Objetivo:** el entrenamiento corriendo. Requisito de la materia.

LoRA congela ~99% de los pesos y entrena solo los adaptadores. Con el modelo de 7B en 4-bit
(~5 GB) el entrenamiento se mantiene en 12-14 GB, dentro de los 24 GB del M4 Pro.

- Empezar con **10 iteraciones** para verificar que el pipeline entero corre, antes de lanzar
  las 600. El intento anterior nunca llegó a esta línea.
- Hiperparámetros de partida: los de `viejo/train.py`, recalibrados al tamaño real del dataset
- Guardar la curva de loss: es material del informe

**Listo cuando:** `checkpoints/lora_bancos/adapters.safetensors` existe, y la inferencia con el
adaptador cargado da un resultado distinto del zero-shot sobre el mismo comprobante.

---

## F10 · Comparación zero-shot vs fine-tuned

**Objetivo:** el entregable académico.

Misma medición de F7, mismos 30 comprobantes, ahora con el adaptador. Tabla comparativa campo
por campo.

**Si el fine-tuning empeoró algo, se reporta igual.** Un resultado negativo bien medido es un
resultado; un número inflado no. Sobreajuste a los sintéticos es un desenlace posible y
perfectamente defendible si se muestra con datos.

**Listo cuando:** existe la tabla comparativa, con N declarado, la curva de loss, y una
conclusión escrita sobre qué campos mejoraron y cuáles no.

---

# BLOQUE C — Integración

## F11 · Enchufar la IA a la web

**Objetivo:** que la carga de comprobantes deje de ser manual.

FastAPI local, modelo cargado una sola vez al arrancar y mantenido en memoria. Next.js le manda
la imagen y recibe los 16 campos.

**La extracción propone, no dispone.** Los campos llegan precargados al formulario de F5 y una
persona confirma. Con volumen alto se puede autoconfirmar cuando la confianza es alta, pero
**recién después de que F10 demuestre que ese campo lo merece.** Antes no.

Manejo de PDFs: convertir a imagen y usar el mismo camino. Son minoría.

**Listo cuando:** se sube una foto, aparecen los campos completos, se confirman, y el
comprobante entra en la conciliación.

---

## F12 · API de deudas

**Objetivo:** conectar con el sistema donde vive la deuda.

Última fase a propósito. Hasta acá el sistema **no manda información a ningún lado**: solo
compara y opina. Recién con la conciliación funcionando y confiable tiene sentido que otro
sistema consuma sus conclusiones.

Pendiente de definir: qué API es, qué expone, en qué dirección va la información.

---

# Resumen

| Fase | Qué deja | Bloque |
|---|---|---|
| F0 | Proyecto que arranca, datos fuera de git | A |
| F1 | Esquema con el doble cobro imposible por diseño | A |
| F2 | 2822 movimientos importados sin un importe mal leído | A |
| F3 | Fixtures con los 6 estados y respuesta conocida | A |
| F4 | Motor de conciliación con tests | A |
| **F5** | **Sistema usable con carga manual** ← hito | A |
| F6 | 30 comprobantes con verdad confirmada | B |
| F7 | Baseline zero-shot medido | B |
| F8 | Dataset sintético en el formato correcto | B |
| F9 | Adaptador LoRA entrenado | B |
| **F10** | **Comparación zero-shot vs fine-tuned** ← entregable | B |
| F11 | Carga automática de comprobantes | C |
| F12 | Conexión con la API de deudas | C |

**Los dos puntos donde el proyecto se puede caer:**

- **F2**, porque un importe mal parseado no rompe nada visible: solo produce una acusación
  falsa. Por eso las 29 filas ambiguas se marcan en vez de adivinarse.
- **F8**, porque es exactamente donde murió el intento anterior: un formato de dataset que la
  librería no acepta. Por eso se verifica contra la versión instalada antes de generar nada.
