# Sesión 12 — la medición estaba castigando tipografía, y la verdad tenía errores

**2026-08-11.** El usuario no podía lanzar `lora_v4` (se llevaba la Mac), así que la sesión
fue entera sobre medición e interfaz. Terminó siendo la sesión que **corrigió la verdad de
referencia**, que es lo más caro que tiene el proyecto.

---

## 1. El hallazgo: 14 falsos errores contra 3

`normalizarCampo` comparaba los 13 campos de texto como strings exactos. Medido sobre los 16
apartados, separando los fallos que son **solo** diferencia de mayúsculas:

| Corrida | Fallos de texto | De esos, solo tipografía |
|---|---|---|
| v1 (la vara) | 75 | **3** |
| `lora_v3_final` | 93 | **14** |

```
concepto        9   "varios"           ≠  "Varios"
banco_emisor    4   "Banco De Galicia" ≠  "Banco de Galicia"
banco_receptor  1   "banco macro"      ≠  "Banco Macro"
```

**El LoRA perdía 11 campos más que el base por tipeo.** Los espacios NO aportaban: 0 casos en
las 6 corridas, así que se pliegan mayúsculas y nada más.

> **Decisión del usuario, textual:** *"no me importa cómo lo pone si mayúscula o minúscula, si
> es que está aplicamos un uppercase o un lowercase y listo. Lo importante es que ponga los
> campos en el lugar correcto."* Y explícitamente: **también contra el Excel.**

Había un test que fijaba lo CONTRARIO a propósito, escrito como alarma: *"si algún día se
decide plegar mayúsculas, que sea a propósito y no un efecto lateral"*. Funcionó: obligó a que
la decisión pasara por acá.

### Dónde vive el plegado, y dónde NO

`normalizarCampo` (comparación) sí. **`paraColumna` (lo que se escribe en la base) no.**
Plegar al guardar reescribiría lo que tipeó una persona en `/revisar`. Hay un test nuevo que
lo fija para que nadie lo mueva.

También se plegó donde el usuario pidió:
- `/encontrar`: `lower()` a los dos lados de `nro_transaccion = referencia`. Hoy no cambia
  ningún resultado —ninguna fila del extracto tiene letras— pero es el join del 90%.
- `motor.ts`: el COELSA del escalón 1. **4 comprobantes lo tienen en minúsculas y los 74
  movimientos en mayúsculas**: hoy da 0 matches por los dos caminos, pero con datos reales
  sería una verificación perdida. Fue con test primero, como manda la regla del motor.

---

## 2. Los errores en la verdad de referencia

El CUIT del receptor es el del usuario, así que debería repetirse igual en los 51. Estaba
escrito de **8 formas distintas**:

```
20-10409660-4   24  ✅ 11 dígitos          20-1126081-9   4  ❌ 10 dígitos
20111260819      6  ✅ 11                  20-1040960-4   2  ❌ 10
20-11126081-9    3  ✅ (mismos dígitos)    2706108679     1  ❌ 10
20104096604      2  ✅ (mismos dígitos)    20-11260819-9  1  ⚠️ guion corrido
2850795040094731285108  →  comprobante 117: un CBU guardado en el campo del CUIT
```

**9 comprobantes con el CUIT del receptor mal, y uno con el dato correcto en la casilla
equivocada.** `cuit_receptor` es uno de los 16 que se miden.

---

## 3. La medición, corregida dos veces

Primero por el plegado, después por las correcciones que hizo el usuario a mano.

| Corte | Publicado (ses. 11) | Tras plegar | **Tras corregir la verdad** |
|---|---|---|---|
| **Sin `tipo_operacion`** | v1 67,5 · LoRA 63,3 | 68,8 · 69,2 | **v1 68,3 · LoRA 70,8** |
| **Sin Mercado Pago** | 50,9 · 58,0 | 52,7 · 64,3 | **v1 52,7 · LoRA 66,1** |
| Los 6 de la conciliación | 74,0 · 80,2 | — | **v1 76,0 · LoRA 82,3** |
| Global (con el bug de vocabulario) | 69,1 · 59,4 | 70,3 · 64,8 | **v1 69,9 · LoRA 66,4** |

**Conclusión que se dio vuelta:** la sesión 11 cerró con "el LoRA perdió en el promedio". En el
corte que saca el bug de vocabulario, **el LoRA está arriba del base: 70,8% contra 68,3%.**
Fuera de Mercado Pago la ventaja es de **+13,4 puntos** (era +7,1).

Las correcciones del usuario **subieron al LoRA y bajaron al base**: sus errores estaban
contando como fallos del modelo cosas que el modelo había sacado bien.

`nombre_receptor` sigue siendo la anomalía sin explicar: **1/16** contra 9/16 del base.

> ⚠️ **12 de los 16 apartados se corrigieron el 11-ago.** Cualquier número anterior a esta
> sesión está medido contra otra verdad. No mezclar.

---

## 4. `/revisar`: el chequeo de forma y el repaso

### La migración 007 y por qué existe

`motivosDeFormato()` (en `lib/revision.ts`, lógica pura y testeada) marca las formas
imposibles: CUIT que no da 11 dígitos, CBU/CVU que no da 22, y el texto `null`/`N/A`/`none`
guardado como si fuera un valor. De 51 revisados, marcaba **22**.

Pero un largo raro no siempre es un error: si el comprobante muestra el número cortado o
enmascarado, lo guardado es correcto. Sin dónde anotar "ya lo miré", esos casos volverían a
aparecer para siempre y la lista nunca llegaría a cero. De ahí
`comprobante.formato_aceptado_en` y el botón **Guardar igual**.

⚠️ **El chequeo vive en TypeScript, no en SQL.** Lo usan la lista, la pantalla de edición y el
guardado; tenerlo escrito dos veces era la forma segura de que se desincronizaran. La cola de
`/revisar` se arma trayendo las 51 filas y filtrando en TS.

### Dos bugs del recorrido, los dos reportados por el usuario

1. **La cola se reordenaba al guardar.** Se ordenaba por `revisado_en`, y guardar lo pone en
   `now()`: el comprobante saltaba al final y "el que sigue" pasaba a ser otro en cada
   guardado. **Ahora la cola se ordena solo por `id`, que no se mueve.** Las pestañas ya
   separan pendientes de revisados; agrupar de nuevo en la cola no aportaba y rompía.
2. **`proximo` moría en una cola vacía.** Con los 51 ya revisados, "pendientes" está vacío, y
   una URL sin `?filtro=` caía ahí, devolvía `null` y guardar terminaba en la lista. Ahora el
   default es `todos` y, si el filtro se queda sin nada, se sigue por la cola completa.

Los tres tests que lo fijan fallaron antes del arreglo y pasan después.

### Dos trampas de la plataforma que costaron tiempo

- **React no renderiza el `value` de un `<button>`.** El plan era
  `<button name="aceptar" value="1">` y dejar que el navegador mandara el par del botón
  apretado; el HTML salía sin el `value`, y la documentación de Next instalada no garantiza
  que el submitter llegue al `FormData` de `useActionState`. **Se resolvió con un `<input
  type="hidden">` que escribe el `onClick`** — un hidden siempre viaja.
- **Backticks adentro de un template literal cortan el string.** Pasó DOS veces, las dos en
  comentarios SQL que citaban una función (`` `lower()` ``, `` `revisado_en` ``). El error
  sale lejos del lugar: `Expected ',', got 'revisado_en'`. **En SQL embebido, no citar con
  backticks.**

---

## 5. La carga manual NO sirve para entrenar — 4 cortes, ninguno avisa

El usuario pidió cargar comprobantes reales para entrenar mejor. `/comprobante` es esa
pantalla, pero se siguió el camino completo y **lo que se carga a mano nunca llega al
dataset**:

| # | Qué pasa | Dónde |
|---|---|---|
| 1 | La imagen va a `web/comprobantes/`, pero el visor solo mira `ia/comprobantes/` y `ia/sinteticos/imagenes/` | `acciones.ts:21` vs `imagen/route.ts:16` |
| 2 | Consecuencia: **la imagen da 404** en `/revisar` | — |
| 3 | `reales.py` filtra `corrida_base <> 'sintetico'`; en SQL eso es **NULL** cuando la columna es NULL, y un comprobante manual la tiene NULL ⇒ **queda afuera del dataset sin un error** | `reales.py:56` |
| 4 | `cargarComprobante` no escribe `revisado_en`, así que tampoco pasa el `revisado_en IS NOT NULL` de `reales.py` | `revision.ts` |

Hoy no rompió nada porque los 71 comprobantes son `origen='ia'`. **Queda sin arreglar**, con el
plan escrito: imagen a `ia/comprobantes/`, `revisado_en` al cargar, incluir los manuales en
`/revisar`, y `IS DISTINCT FROM` en `reales.py`.

---

## 6. Por qué NO se tocó `revisado_en` de los 20 sin repasar

El usuario pidió poner los que no repasó como pendientes. **Se frenó y se explicó**, porque
`revisado_en = NULL` arrastra tres cosas:

1. `reales.py` los sacaría del dataset: entrenaría con 31 en vez de 51.
2. **La partición cambiaría.** Los 16 apartados salen de un sorteo con semilla fija **sobre el
   conjunto de revisados**; si el conjunto cambia de tamaño, los 16 pasan a ser otros
   comprobantes y **ningún número vuelve a ser comparable**. Se perdería la vara.
3. `/corridas` y `comparar-lora.ts` filtran por `revisado_en`: la comparación se achicaría.

El usuario decidió **no cambiarlos** y seguir desde donde quedó. Las tres opciones quedaron
escritas para cuando vuelva (columna `repasado_en` / filtro por fecha / lo pedido).

---

## 7. Estado al cerrar

```
51/51 reales repasados el 11-ago   ·  0 CUIT fuera de 11 dígitos
0 CBU fuera de 22                  ·  0 usos de "Guardar igual"
173/173 tests                      ·  tsc limpio
migración 007 aplicada en conciliador y conciliador_test
```

**El usuario repasó los 51 en la misma sesión y no dejó ninguno "aceptado sin arreglar".** Es
la primera vez que la verdad de referencia pasa un chequeo de forma completo.

⚠️ **Los porcentajes se movieron cuatro veces a lo largo del día** (plegado → correcciones →
más correcciones → repaso completo). Los de la §3 son los del cierre, sobre la verdad final.
**Antes de citar cualquiera, rehacerlos:** `cd web && node --env-file=.env.local comparar-lora.ts`.

## 8. Lo que se descubrió al final y quedó SIN DECIDIR

Con la verdad ya limpia apareció **el mismo problema de las mayúsculas, con los guiones**:

| Corrida | Fallos en campos numéricos | Solo separadores |
|---|---|---|
| v1 (base) | 40 | **0** |
| `lora_v3_final` | 28 | **10** |

`20-27705919-4` ≠ `20277059194`. Mismos dígitos, distinta puntuación: **~4 puntos que el LoRA
pierde y el base no.** Propuesta: comparar los cuatro campos de CUIT y CBU **solo por dígitos**,
nunca `coelsa_id` ni `referencia` (alfanuméricos, se les borrarían las letras). **Sin respuesta
del usuario** — está en el ESTADO ACTUAL como sección 🟡.

Segundo pendiente, de 10 segundos: el comprobante **126 (`044.jpeg`)** tiene
`cuit_receptor = 20-11260819-9` y el resto de esa familia `20-11126081-9`. Los dígitos no
coinciden y **es el único CUIT de receptor que no matchea con ningún otro**. Puede ser
legítimamente otra cuenta.

**Archivos nuevos:** `migraciones/007_formato_aceptado.sql`.
**Tocados:** `lib/revision.ts` (+`motivosDeFormato`, `cola`, `entra`, `proximo`,
`aceptarFormato`, `ETIQUETAS`), `lib/importar-comprobantes.ts`, `lib/motor.ts`,
`app/acciones.ts`, `app/revisar/page.tsx`, `app/revisar/[id]/{page,formulario}.tsx`,
`app/encontrar/page.tsx`, y los tests de los tres primeros.

**Lo que NO se hizo:** `lora_v4` (el usuario se llevaba la Mac), las plantillas sintéticas de
más bancos, y el arreglo de la carga manual.
