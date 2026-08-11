<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

# 🔄 2026-08-07 · RE-ESPECIFICACIÓN — el usuario consultó con la empresa

**Esto cambia el alcance y el orden del proyecto.** Lo que sigue viene de cómo la empresa
trabaja de verdad, no de lo que se había supuesto.

### Lo que dijo la empresa

1. **Se guardan TODOS los campos del comprobante, no cinco.** Cae el hallazgo de la sesión 3 de
   que "el motor solo mira 5 de los 16". Sigue siendo cierto *para el motor*, pero el negocio
   guarda los 16 y la IA los tiene que sacar todos bien. **La medición de F7/F10 pasa a ser
   sobre los 16 campos.**
2. **La cascada real de identificación**, en palabras del usuario:
   ```
   1. nro de transacción + CUIT   → si aparece, se chequea monto y fecha → 90% confiable
   2. si no está                  → solo fecha y monto                   → 50% confiable
   ```
3. **La comparación extracto ↔ comprobantes va por código, sin IA.** Coincide con el diseño
   actual.
4. **Los que no cruzan se le muestran al usuario** para que decida a mano.
5. **Todo en la web.**
6. **Looker Studio**, recomendado por el profesor.

### ⚠️ La premisa que NO se verificó — medido sobre los 2822 movimientos

El usuario dijo que *"los últimos números de transacción se pone el número del CUIT de la otra
persona"*. **Es falso para la columna `NRO TRANSACCION` de este extracto:**

```
nro_transaccion adentro del CUIT:   0 de 2586   ← nunca, en ninguna posición
CUIT en la DESCRIPCION:          2586 de 2822   ← 91,6%
nro_transaccion presente:        2822 de 2822   ← 100%
nro_transaccion distintos:       2787 de 2822   ← 98,8% único
largo de nro_transaccion:        3 a 10 dígitos ← un CUIT necesita 11: NO ENTRA
```

**El dato existe, pero en otra columna.** La lógica se implementa igual; cambia de dónde sale
el CUIT (de `DESCRIPCION`, que es de donde `extracto.ts` ya lo parsea).

#### 🔎 PENDIENTE — el usuario insiste en que el CUIT está en `NRO TRANSACCION`

Dice que están **los últimos dígitos** del CUIT, no todos. Se probaron **cinco** formas sobre
los 2822 movimientos y **ninguna da señal por encima del azar**:

| Hipótesis | Resultado |
|---|---|
| el `nro_transaccion` entero es el sufijo del CUIT | 0 de 2586 |
| el `nro_transaccion` entero está dentro del CUIT | 0 de 2586 |
| el `nro_transaccion` **termina** con los últimos k del CUIT (k=3..8) | 3 en k=3 — el azar predice 3 |
| el `nro_transaccion` **contiene** los últimos k del CUIT (k=4..6) | 2 en k=4 — azar |
| el sufijo es constante por cuenta (sería el CUIT **propio**) | no: 100 sufijos distintos de 2 dígitos sobre 100 posibles, reparto uniforme |

Se comporta como un **contador secuencial**, no como algo que codifique un CUIT.

**Lo que hace falta para cerrarlo, y solo lo puede dar el usuario:** abrir el Excel, encontrar
UNA fila donde vea los dígitos del CUIT, y decir **en qué columna y en qué posición** están.
No hace falta que mande el valor — alcanza con la ubicación y la forma.

**Si aparece, hay que agregarlo al motor** como parte de la regla 1.

**Y la regla del usuario es mejor que la que está construida.** El motor actual usa el COELSA
como identificador de máxima confianza y el COELSA está en **84 de 2822 filas (3%)**;
`nro_transaccion` está en el **100%** y es 98,8% único.

**Lo que sigue sin poder verificarse:** que el `N° de operación` del comprobante sea el mismo
número que el `NRO TRANSACCION` del extracto. Los 52 comprobantes son de otro período y otra
fuente. **Es el supuesto del que depende toda la regla del 90%.**

> ✅ **Resuelto el 2026-08-07: no se puede y no hace falta intentarlo.** El usuario confirmó
> que **el Excel y los 52 comprobantes son dos ejemplos sin relación entre sí**. Cruzarlos no
> tiene sentido. Va a conseguir **un caso real** —extracto y comprobantes de la misma fuente y
> el mismo período— y recién con eso se valida la regla del 90% y se entrena con datos propios.
> **No volver a perseguir este cruce con los archivos actuales.**

### 🎯 La prioridad, en palabras del usuario (2026-08-07)

> *"Concentrémonos en sacar todo del comprobante, que es lo más importante. Lo demás solo es
> lógica de comparación matemática."*

**La calidad de extracción de los 16 campos es el centro del proyecto.** La conciliación es
aritmética y ya está resuelta. Todo lo que no mejore la extracción es secundario.

### Looker Studio — investigado, y choca con la regla 2

**Looker Studio consulta desde los servidores de Google, no desde la Mac.** Para conectarlo a
Postgres habría que exponer la base a internet y abrir el firewall a `142.251.74.0/23`
([doc oficial](https://docs.cloud.google.com/looker/docs/studio/connect-to-postgresql)). Eso
rompe la regla 2 y la de "sin deploy".

**Decisión tomada:** se usa Looker Studio con **métricas del modelo y datos sintéticos** —
accuracy por campo zero-shot vs fine-tuned, curva de loss, comparación de los 4 prompts, demo
del tablero con comprobantes de `faker`. Ningún dato bancario real sale de la máquina, y es
además el entregable académico en formato visual.

### Las tres decisiones tomadas

| Decisión | Detalle |
|---|---|
| **La pantalla de revisión va ANTES de seguir el fine-tuning** | Es la que produce las etiquetas reales. Reemplaza a `verdad_referencia.xlsx`, trabada desde la sesión 3, y lo hace mejor: se ve la imagen al lado de los campos. Sin etiquetas reales no hay forma de medir si el fine-tuning sirve en comprobantes de verdad — solo contra sintéticos, que prueban que el modelo aprendió el simulador |
| **Looker Studio con métricas del modelo + sintéticos** | Ver arriba |
| **`motor.ts` se reescribe con la cascada de la empresa** | 90% / 50%. **TDD primero**, como la primera vez. Los 32 tests actuales se rehacen |

> **Expectativa aclarada al usuario:** *"que lo tome como aprendizaje para la próxima"* no es
> aprendizaje en línea. LoRA no aprende comprobante por comprobante. La pantalla **acumula**
> correcciones en un dataset y **cada tanto se re-entrena**. El modelo mejora en tandas.

### Lo que se construyó después de la re-especificación

| Archivo | Qué es |
|---|---|
| `web/migraciones/003_revision.sql` | `revisado_en`. (Su `extraccion_ia` lo reemplazó la 004) |
| `web/migraciones/004_corridas.sql` | Tablas `corrida` y `extraccion`: **varias extracciones por comprobante**, que es lo que permite comparar |
| `web/src/lib/importar-comprobantes.ts` | JSONL → base. Lee las dos formas (`{archivo,campos}` y `{images,messages}`) |
| `web/src/app/revisar/` | Lista + detalle: imagen a la izquierda, 16 campos editables a la derecha |
| `web/src/app/api/comprobante/[id]/imagen/route.ts` | Sirve el JPG de a uno, sin publicar la carpeta |
| `web/src/app/corridas/page.tsx` | Comparación entre corridas: descripción, linaje, métricas por campo |
| `acciones.ts::guardarRevision` | La corrección humana. Escribe SOLO las columnas tipadas |

**El modelo de datos, que es lo importante:**

```
extraccion.campos    lo que contestó el modelo, por corrida. NUNCA se pisa
comprobante.<campos> la verdad: arranca igual y la corrige una persona
comprobante.corrida_base   contra cuál se compara la corrección
```

Qué campos estaban mal **no se guarda**: sale de comparar los dos. Mismo criterio que
`sin_comprobante` — no se guarda lo que se puede preguntar.

### Cargado en la base

```
72 comprobantes: 52 reales + 20 sintéticos
5 corridas con su linaje: sintetico · v1 → v2 → v3 (base) → v4

campos con valor (crudo, sobre 52 × 16 = 832):
  v1 703 · v2 768 · v3 795 · v4 658
```

> ⚠️ **Estos números NO son los 591/637/664/528 de la sesión 3.** Aquéllos contaban campos que
> **pasan validación de formato**; éstos cuentan campos **con algo escrito**. Los dos son
> legítimos y miden cosas distintas. Ninguno de los dos mide **aciertos** — para eso hace falta
> la corrección humana, y por eso la pantalla `/revisar` es la pieza central.

### Cuatro bugs propios encontrados y corregidos al cargar

| Bug | Detalle |
|---|---|
| `invalid input syntax for numeric: "$81.687,80"` | El crudo del modelo no entra en columnas tipadas. Se reusó `parsearImporte` de `extracto.ts` en vez de escribir otro parser; lo ambiguo va a NULL |
| `numeric field overflow` | El modelo a veces devuelve un CBU de 22 dígitos como `monto`. `NUMERIC(14,2)` admite 12 enteros: se acota a NULL, **no se trunca** — truncar sería inventar un importe |
| FK en cascada en `corrida` | Cargar v1,v2,v4,v3 falla: v4 referencia a v3 que aún no existe. **Cargar en orden de dependencia** |
| Las páginas seguían consultando `extraccion_ia` | La 004 la eliminó. `tsc` no lo agarra: el SQL es un string. Solo se ve corriéndolo |

### Verificado

```
$ curl /revisar            HTTP 200 · 72 comprobantes
$ curl /revisar/<id real>  HTTP 200 · imagen 49174 bytes
$ curl /corridas           HTTP 200 · linaje y tabla por campo presentes
$ pnpm test                112 pass · 0 fail
$ tsc --noEmit             sin errores   ·   $ pnpm lint   sin quejas
```

**La detección de correcciones se probó rompiendo un sintético a propósito:** se le cambió el
monto y el nombre del emisor, y la página marcó los dos inputs en ámbar con el texto *"la IA
había puesto: …"*. Al revertir, 0 diferencias.

**Verificación cruzada imagen ↔ base, posible solo con sintéticos:** la imagen del Macro dice
`$ 292.301` / `21/07/2026 - 19:16` y la base tiene `292301.00` / `2026-07-21` / `19:16`. La
canonización de `ia/generar.py` funciona.

> **No se pudo verificar el aspecto visual.** La extensión de Chrome no está conectada, así que
> no hubo captura de pantalla: se revisó el HTML servido, que confirma que los elementos están,
> pero no cómo se ven.

### 🐛 "No puedo guardar la revisión" — no era eso, eran DOS bugs míos

El usuario reportó que no podía guardar. **El guardado funcionaba perfecto**: el log mostraba
5 POST con 200 y `revisado_en` estaba escrito en la base. Los problemas reales eran otros dos:

**1. La página no daba ninguna señal.** Se guardaba y todo quedaba igual, así que apretó el
botón cinco veces. Arreglado: `guardarRevision` ahora hace `redirect()` **al próximo
comprobante sin revisar**, con un cartel verde. Además convierte revisar 52 en una sola
secuencia, sin volver a la lista.

**2. `monto`, `fecha` y `hora` salían como "corregidos" sin que nadie los tocara.** Se comparaba
el **texto crudo** del modelo contra la **columna ya convertida**:

```
hora        ia="21:26"   ↔  columna="21:26:00"   mismo valor
monto       ia="4800"    ↔  columna="4800.00"    mismo valor
coelsa_id   ia="N/A"     ↔  columna=NULL         "N/A" ES vacío: el modelo acertó
```

**Este era el grave.** No solo hacía perder tiempo revisando campos correctos: metía errores
inventados en la tabla de aciertos, o sea **en los números del informe**. Un modelo que sacaba
bien todos los montos habría figurado fallándolos todos.

Arreglado con **`normalizarCampo(campo, valor)`**, exportado de `importar-comprobantes.ts` y
usado por los tres lugares que comparan: el importador, `/revisar` y la tabla de aciertos de
`/corridas`. Tienen que usar el mismo o vuelve a pasar.

> Comprobante 131, el que el usuario revisó: con la comparación arreglada da **0 diferencias**.
> El modelo lo había sacado bien. Los 4 "campos corregidos" eran los artefactos de arriba.

### Filtros en `/revisar`

Tres botones — **Pendientes** (el default), **Revisados**, **Todos** — con el conteo al lado,
por `?filtro=`. Un valor inválido cae en `pendientes`, no rompe. Verificado contra la base:

```
filtro=pendientes → 71 listados        en la base: pendientes 71
filtro=revisados  →  1 listado                     revisados   1
filtro=todos      → 72 listados                    todos      72
```

Con `guardarRevision` saltando al próximo pendiente, el circuito de revisión queda cerrado:
se entra por Pendientes, se guarda, se salta al siguiente, y al terminar la lista queda vacía
con un aviso. Los revisados no vuelven a aparecer.

### 🔎 `/encontrar` — la cascada de la empresa, ya implementada

Pantalla nueva: qué fila y hoja del Excel le corresponde a cada comprobante y **por qué regla**.

**No usa `motor.ts`.** Aquél cruza por `cuenta.cbu`, que sigue en NULL en las tres cuentas, así
que daría `no_verificable` en los 52. La cascada de la empresa **no necesita los CBU**:

```
1. nro_transaccion + CUIT coinciden  → se chequea monto y fecha → 90%
2. si no                             → solo monto y fecha       → 50%
```

**Eso desbloquea algo que estaba trabado desde la sesión 1.** Los CBU dejan de ser necesarios
para ver un resultado.

La pantalla ordena primero los NO encontrados, para que el usuario los busque a mano y avise
con qué dato los encontró — así se ve qué le falta a la regla.

### 📊 El hallazgo medido más importante del día

Cruzando los 52 comprobantes contra los 2822 movimientos:

```
cruzan por monto + fecha exactos ........ 19 de 52
   los mismos, agregando el CUIT ........  0 de 52   ← CERO
cruzan por nro_transaccion = referencia ..  1 de 52
```

**Diecinueve coincidencias de monto y fecha y ninguna sobrevive al CUIT.** Es la firma de
**coincidencias numéricas casuales**, no de transferencias reales — coherente con que los dos
archivos sean ejemplos sin relación. Y es la prueba empírica de por qué la regla del 90% mira
el CUIT antes que el importe: sin ese chequeo el sistema habría reportado **19 falsos
positivos**.

### Notas de Next.js 16 que costaron tiempo

- `params` es una **Promise**, en páginas y en route handlers. Hay que `await`.
- Los tipos `PageProps<'/ruta'>` y `RouteContext<'/ruta'>` **los genera Next**. Al crear una
  ruta nueva, `tsc` falla hasta correr **`pnpm exec next typegen`**.

---
