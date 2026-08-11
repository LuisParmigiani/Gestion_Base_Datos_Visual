# Sesión 13 — el generador sintético: etiquetas verificables, calidad y escala

**2026-08-11.** Se auditó `ia/generar.py` campo por campo, se rehízo el mecanismo que
produce las etiquetas para que no pueda mentir, se agregaron dos perfiles de calidad y se
armó `train_v4.jsonl`. **También se borraron por error 1364 imágenes** — está contado
entero en la sección 6, sin adornos.

---

## 1. Por qué se miró: el pedido

El usuario pidió tres cosas, en sus palabras: que los sintéticos tengan **"las labels
perfectas"**, que **"se parezcan lo máximo posible a los reales"**, y **600 comprobantes,
300 de buena calidad y 300 de menor calidad "que varíen, unos más borrosos que otros"**.
Después, al ver el reparto por banco, cambió el volumen: **mínimo 80 por banco**.

## 2. La auditoría: 7 plantillas limpias, 2 con defectos, 4 problemas transversales

Se leyeron las 10 plantillas comparando lo que dibujan contra lo que declaraban en
`ocultos=[...]`.

| Plantilla | Estado |
|---|---|
| Macro · Galicia · Santander · Naranja X · BBVA · Brubank · Ualá · Personal Pay | ✅ coincidían |
| **Mercado Pago** | ⛔ `hora` |
| **Banco Nación** | ⛔ `banco_receptor` · 🟡 `nombre_receptor` · 🟡 `hora` |

**Mercado Pago** dibujaba la fecha larga —que termina en `a las 14:35 hs`— y etiquetaba
`hora: null`. Le enseñaba a **no leer** una hora que está escrita, en la plantilla que
entonces pesaba el 50% del dataset.

**Banco Nación** dibujaba `dat["banco_rec"].replace("Banco ", "").upper()`, o sea
`GALICIA`, y etiquetaba `Banco Galicia`. No es un tema de mayúsculas: le pedía al modelo
escribir una palabra que no está en la imagen.

Transversales:

1. **`concepto` era la constante `"Varios"`** en las 300 sintéticas. El modelo no podía
   aprender a *leer* un concepto, solo a *escribir* "Varios". Y es el campo que le pone el
   techo a la meta del 98%.
2. **`moneda` siempre `ARS`**, y solo BBVA la escribía con letras.
3. **Mercado Pago nunca mostraba centavos** (`con_decimales=False` fijo).
4. **La referencia de Naranja X era un `uuid4`** con guiones. Ningún banco emite eso: es un
   formato inventado que el modelo aprendía como válido.

### Por qué el chequeo que ya existía no los vio

`verificar_templates()` comparaba `ocultos=[...]` contra el código de dibujo **con regex
sobre el fuente**. Buscaba `%H:%M` dentro del cuerpo de la plantilla, y en Mercado Pago la
hora entra por `fmt_fecha_larga_ar()`. **Era ciego a todo lo que pasara por un helper.**
Se borró (55 líneas).

## 3. El arreglo de fondo: `Lienzo`

El problema no eran los dos bugs sino que había **dos verdades** sobre cada plantilla —el
código que dibuja, y una lista escrita a mano al lado del `return`— y podían separarse en
silencio.

`Lienzo` envuelve `ImageDraw` y anota todo el texto que dibuja:

- `d.campo("cuit_receptor", xy, texto)` dibuja **y registra**.
- `d.logo(logo_santander, x, y)` registra `banco_emisor`: el logo es la prueba de quién
  emite, y así una plantilla nueva no puede olvidárselo.
- `ocultos` **dejó de escribirse**: es `set(CAMPOS) - lienzo.visto`.
- `leido=` cubre el caso de Naranja X, que parte el monto en dos dibujos (los centavos van
  aparte y en chico).

Y `_gt` verifica **las dos direcciones** contra el texto realmente dibujado:

```
campo con valor  → ese valor TIENE que leerse en la imagen
campo en null    → ese valor NO tiene que leerse en la imagen
```

Comparando también solo dígitos, porque la etiqueta dice `20277059194` y la imagen
`20-27705919-4`. Cuatro campos quedan fuera del cotejo literal (`_NO_LITERALES`) porque no
se dibujan como valor crudo: `fecha` (formato argentino), `banco_emisor` (el logo),
`tipo_operacion` (el título) y `moneda` (el símbolo).

**Se verificó reinyectando los bugs reales**, no asumiendo:

```
✅ Mercado Pago: `hora` se lee en la imagen ('08:16') y la etiqueta lo deja en null
✅ Banco Nación: `banco_receptor` se etiqueta 'Banco Galicia' pero eso NO se lee en la imagen
✅ Banco Santander: `cuit_emisor` se etiqueta '27381796571' pero eso NO se lee en la imagen
✅ Banco Macro: `cbu_cvu_receptor` se etiqueta '000000310040479...' pero eso NO se lee
```

El tercero es el que importa de verdad: es el modo de falla que **acusa a un cliente
honesto** con un CUIT inventado que pasa cualquier validación de formato.

### Un falso positivo del chequeo nuevo, y su arreglo

Al subir Santander de 55 a 80 ejemplos, el generador se plantó diciendo que la hora `11:07`
se leía en la imagen. Era **mentira**: `Cuenta débito: CTA $ 811-075716/5` tiene dígitos
`8110757165`, que **contiene la subcadena** `1107`. El cotejo por dígitos comparaba
subcadenas.

Ahora compara **números completos** (`_NUMERO_ESCRITO`), y `hora` no usa el cotejo por
dígitos porque su forma canónica `HH:MM` ya es idéntica a la dibujada. Con 4 dígitos
sueltos era el único campo que podía chocar por azar contra un número de cuenta.

> **La lección, otra vez:** un chequeo que nunca falló no está probado. Los tres que sí
> sirven se probaron rompiéndolos a propósito.

## 4. Calidad: se dibuja en grande y se entrega chico

### La medición que decidió todo

Antes de escribir una línea se midió con el procesador instalado
(`Qwen2VLImageProcessor` del snapshot local) a qué resolución consume la imagen el modelo.
**No hay resize a tamaño fijo: es un token cada 28×28 px, así que los tokens escalan con el
área.**

| Tamaño final | Tokens | |
|---|---|---|
| 540×882 | 608 | ✅ |
| 820×1340 | 1.392 | ✅ |
| 1170×1912 (screenshot real de iPhone) | 2.856 | ⚠️ |
| 1640×2680 | 5.664 | 💀 zona que mató corridas |

`max_pixels: 12845056` → tope teórico 16.384 tokens. **El tope real es el del
entrenamiento: 1.848 probado, 3.078 mortal.**

De ahí sale la regla: **se puede dibujar a cualquier resolución mientras la imagen guardada
vuelva a bajar.**

### Cómo quedó

- **`ESCALA = 2`**: se dibuja al doble. Las plantillas siguen escritas en coordenadas de
  820 de ancho y no se tocó ninguna: `Lienzo` multiplica la geometría y `fnt()` el tamaño
  de fuente. `textlength` divide de vuelta para que las plantillas que alinean a la derecha
  sigan funcionando.
- **`finalizar()`** entrega en dos perfiles:
  - **Nítido**: baja a 820 con LANCZOS, JPEG 90-97. Bajar de 2× es lo que da el suavizado
    de un screenshot real, en vez del borde duro de dibujar al tamaño final.
  - **Degradado**: una `severidad` continua entre 0 y 1 mueve **a la vez** el ancho
    (760→480), el desenfoque (0→0,9 px) y la compresión (JPEG 72→32), más rotación leve en
    el 35%. **No hay dos degradados iguales.**

### El piso de legibilidad es una decisión, no un descuido

El primer intento bajaba a 380 px con más desenfoque. Mirando el resultado, **el CBU de 22
dígitos quedaba en el borde de lo ilegible** — y eso es el mismo error que toda esta sesión
persigue, entrando por la puerta de la calidad: si el número no se lee, la etiqueta le
enseña a inventarlo. Se subió el piso a 480 px y se verificó mirando el peor caso del lote.

## 5. 80 por banco: por qué se abandonó la proporción real

`PESOS` copiaba la distribución de los 51 reales (Mercado Pago 25, Macro 8, Galicia 6,
Santander 5, Nación 2, Naranja X 2, Brubank 1, y **cero** de BBVA, Ualá y Personal Pay, a
los que se les dejaba peso 1). En 600 ejemplos eso dejaba **tres bancos con 11**.

El usuario pidió mínimo 80 cada uno. Con 10 bancos el piso obliga a 800 como mínimo
aritmético, y se eligió **80 exactos para todos**.

El razonamiento: **el ejemplo número 200 de Mercado Pago casi no agrega; el número 40 de
BBVA sí.** Además la medición de F10 ya venía diciendo que el modelo base es un
especialista en Mercado Pago y mediocre en el resto — que es exactamente lo que esa
proporción enseñaba. Parte del sesgo real vuelve solo, porque los reales que suma
`reales.py` siguen siendo mayormente Mercado Pago.

`PESOS` se borró; la bolsa es `list(TEMPLATES.values())`. La distribución real medida quedó
anotada en el comentario, que es donde sirve.

## 6. ⛔ Se borraron 1364 imágenes por error

**Qué pasó.** Después de una corrida fallida quedaron imágenes a medias. Se corrió una
limpieza de huérfanas que comparaba las rutas del disco (**relativas**, salidas de un
`glob`) contra las que guardan los `.jsonl` (**absolutas**). Ninguna coincidió, todas
quedaron marcadas como huérfanas, y se borraron las 1364. Están en `.gitignore` (`*.jpg`) y
`unlink()` no pasa por la papelera: **no hay recuperación.**

**Qué NO se perdió** — verificado archivo por archivo:

- Los **51 comprobantes reales** de `ia/comprobantes/`. Son `.jpeg` y otro directorio.
- **`test_reales.jsonl`**, la vara: 16/16 imágenes existen.
- Todos los `.jsonl` con sus etiquetas.
- La base, los checkpoints, `lora_v3`.

**Qué se perdió.** Las 300 imágenes sintéticas de `train_v3.jsonl` y las de `train_v2`,
`train_v1_ROTO` y `train.jsonl` — el mismo pozo de 637. **No son reproducibles**: salían
del generador viejo, con otra secuencia de azar.

**Qué cuesta.**

- `train_v3.jsonl` ya no sirve para entrenar. Estaba marcado como **bloqueante a
  reemplazar** desde la sesión 12 ("tiene las etiquetas de ANTES del repaso del 11-ago") y
  esta sesión demostró que su mitad sintética arrastra los cuatro defectos de arriba. Era
  material que se iba a tirar igual.
- **Lo que sí se pierde de verdad: reproducir exactamente la corrida de `lora_v3`.** Los
  números de la tabla 🎯 siguen valiendo —se midieron contra `test_reales.jsonl`, intacto— y
  los pesos del checkpoint también. Pero el dataset exacto con el que se entrenó ya no
  existe, y eso hay que decirlo si alguna vez se publica el número.
- El valor de evidencia de `train_v1_ROTO.jsonl` se conserva casi entero: lo que documenta
  el error metodológico son **las etiquetas inventadas**, y el `.jsonl` está.

**Regla que sale de acá:** ninguna limpieza masiva de archivos sin listar antes qué se va a
borrar y confirmarlo. Y si un cotejo de rutas da "0 coincidencias de 1364", eso no es un
resultado, es un síntoma.

## 7. `reales.py`: la guarda de tokens

Al armar `train_v4.jsonl` apareció que `reales.py` **volvió a meter los gigantes**:
`015.jpeg` (3.534 tokens) y `033.jpeg` (3.078) — exactamente los dos que la sesión 8 anotó
como los que matan el proceso sin dejar traceback. `train_v3` los tenía afuera porque venía
de `train_v2_sin_gigantes`, pero `reales.py` no sabía nada de eso: toma todos los revisados
que no estén apartados.

**Acordarse no es una estrategia.** Ahora `reales.py` mide cada imagen real y, si pasa
`TOPE_TOKENS = 1800`, escribe una copia achicada en `ia/comprobantes_reducidos/` y apunta
el dataset ahí. El original nunca se toca: lo muestra `/revisar` y es el comprobante que la
persona miró para escribir la verdad.

**La vara se entrega SIEMPRE en tamaño original** (`registro(f, para_entrenar=False)`). El
tope es un problema del entrenamiento, no de la inferencia —los 51 se extrajeron enteros
sin drama— y achicar un apartado cambiaría la medición en silencio.

## 8. Lo que quedó

`ia/sinteticos/sinteticos_800.jsonl` — 800 sintéticos, 80 por banco, 40 nítidos y 40
degradados en cada uno. 44 MB.

`ia/sinteticos/train_v4.jsonl` — **842 ejemplos** (800 sintéticos + 42 reales), máximo
**1.782 tokens**, cero por encima del tope, ningún apartado filtrado, 9 usando copia
reducida.

La vara se regeneró con la verdad repasada: **cambiaron 25 de sus 256 campos** respecto de
la versión del 7 de agosto. Es la confirmación concreta de por qué ningún número anterior
al 11-ago es comparable.

## 9. Lo que se mudó acá desde `BITACORA.md`

Estas dos tablas estaban en el ESTADO ACTUAL y son de la sesión 12 (medición del 11-ago con
la verdad ya repasada). Se guardan acá porque **`sesion-11` tiene los números viejos**, que
quedaron superados por el plegado de mayúsculas y las correcciones del usuario.

⚠️ **Nada de esto es comparable con lo que salga de `lora_v4`**: la vara se regeneró y
cambiaron 25 de sus 256 campos. Hay que volver a medir el base y `lora_v3_final` contra la
vara nueva antes de comparar nada.

### `lora_v3` contra el base — 16 apartados, 256 campos, 2026-08-11

| Corte | v1 (base) | `lora_v3_final` |
|---|---|---|
| **Sin `tipo_operacion`** ← el corte limpio | 67,9% | **70,4%** |
| **Sin Mercado Pago** | 53,6% (60/112) | **66,1%** (74/112) |
| **Los 6 de la conciliación** | 76,0% | **82,3%** (79/96) |
| Solo Mercado Pago | **81,9%** | 66,0% |
| Global (arrastra el bug de vocabulario) | **69,5%** | 66,0% |

**El base es un especialista en Mercado Pago y mediocre en el resto; el LoRA es parejo.**
Los 16 apartados eran 56% Mercado Pago, así que el global medía sobre todo una entidad.
**Reportar siempre desagregado por entidad.**

Mejoró donde el base inventaba (`cbu_cvu_emisor` 7→12, `cbu_cvu_receptor` 11→15, `concepto`
4→11) y empeoró en texto (`nombre_receptor` 9→**1**, sin explicación).

## 10. Los guiones del CUIT — decidido y medido

El diagnóstico venía de la sesión 12: de los 28 fallos de `lora_v3_final` en campos
numéricos, **10 eran solo puntuación** (`20-27705919-4` ≠ `20277059194`), y de los 40 del
base, **cero**.

**Decisión: se pliegan.** `normalizarCampo` compara los dos CUIT y los dos CBU solo por sus
dígitos (`SOLO_DIGITOS`). ⛔ `coelsa_id` y `referencia` quedan afuera: son alfanuméricos y
sacarles los no-dígitos les borraría las letras, con lo que dos IDs distintos pasarían a ser
el mismo — **un falso acierto es peor que un falso error**. Lo que se GUARDA conserva lo que
tipeó la persona: el plegado es solo para comparar, igual que con las mayúsculas.

Estaba implementado con 5 tests sin commitear, incluidos los casos borde que importan: que
dos CUIT distintos sigan siendo distintos, que `no figura` no se convierta en ausencia (si
diera `''` empataría contra una columna en NULL y el modelo inventando texto se premiaría), y
el caso del comprobante 126. **185 tests en verde.**

### La medición después de plegar

| Corte | v1 (base) | `lora_v3_final` antes | **después** |
|---|---|---|---|
| Los 6 de la conciliación | 76,0% | 82,3% | **87,5%** (84/96) |
| Sin `tipo_operacion` | 67,9% | 70,4% | **74,6%** |
| Sin Mercado Pago | 53,6% | 66,1% | **67,9%** |
| Global | 69,5% | 66,0% | **69,9%** |
| Solo Mercado Pago | **81,9%** | 66,0% | 71,5% |

**La prueba de que el plegado corrige un sesgo y no infla un número: los cinco cortes del
base dan exactamente lo mismo que antes.** El base no escribe guiones, así que no podía
ganar nada. Todo el movimiento es dejar de cobrarle al LoRA por cómo escribe un número en
vez de por si lo leyó bien — y con eso pasa a ganarle al base **también en el global**, que
era el único corte donde perdía.

`lora_v3_final` le gana a `lora_v3_mejor` en el corte de conciliación (87,5% contra 84,4%).
Tercera confirmación de que **`mejor/` es red de seguridad contra la divergencia, no un
selector de calidad**.

`nombre_receptor` sigue derrumbado en **1/16** contra 9/16 del base, sin explicación. Es el
único campo donde el LoRA es peor por goleada.

### Sin decidir

- **Los guiones del CUIT.** Sigue sin respuesta desde la sesión 12, y cambia la medición:
  conviene resolverlo antes de fijar cualquier número de `lora_v4`.
- **Plantillas de bancos nuevos** (Cuenta DNI, Prex). Bloqueado por algo real: sin una
  referencia visual, el layout se inventa — que es exactamente el error del `uuid4` de
  Naranja X. Requiere autorización expresa para mirar comprobantes reales localmente, que
  choca con la contradicción de la regla 2 que sigue abierta desde la sesión 3.
