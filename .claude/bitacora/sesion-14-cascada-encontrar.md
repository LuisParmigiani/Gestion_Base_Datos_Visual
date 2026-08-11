# Sesión 14 — los separadores costaban 22 comprobantes, y `/encontrar` se volvió usable

**2026-08-11.** Tres frentes: se cerró la decisión de los guiones que venía pendiente, entraron
7 comprobantes reales nuevos, y `/encontrar` pasó de pantalla de diagnóstico a herramienta de
trabajo. El hallazgo más caro lo encontró el usuario mirando la pantalla, no la máquina.

> ⚠️ **Numeración.** Esta sesión corrió **en paralelo con la 13** (`sesion-13-generador.md`) y
> se numeró después, pero sus §1 a §4 son **anteriores**: la 13 parte de ellas. Los 7
> comprobantes nuevos de la §3 son los que llevan la verdad a 58, que es de donde salen los 42
> reales del `train_v4.jsonl` de la 13; los apartados fijos de la §2 y la guarda de tokens de
> la §4 son las que esa sesión da por hechas. Lo de la §5 en adelante —`/encontrar`, la tabla
> `eleccion` y la cascada— es solo de acá y la 13 no lo menciona.

---

## 1. Los guiones del CUIT — decidido y aplicado

> **Criterio del usuario, textual:** *"quiero que la IA lo escriba como le sea más fácil y que
> luego por código con lower o con if o como se dé se ponga todo de la misma forma; no le
> exijamos cosas que podemos realizar nosotros de manera muy simple."*

Es la misma decisión que las mayúsculas de la sesión 12, ahora para los separadores.
`normalizarCampo` compara `cuit_emisor`, `cuit_receptor`, `cbu_cvu_emisor` y `cbu_cvu_receptor`
**solo por sus dígitos**. ⛔ `coelsa_id` y `referencia` quedan afuera: son alfanuméricos y
quitarles los no-dígitos les borraría las letras.

Detalle que evita un falso acierto: si el valor **no tiene ningún dígito** se cae al texto en
minúsculas. Sin eso, `no figura` daría `''` y empataría con una columna en NULL — el modelo
inventando texto se premiaría como si hubiera acertado.

### La medición se movió, y solo del lado del LoRA

| Corte | Antes (11-ago mañana) | **Ahora** | v1 (base) |
|---|---|---|---|
| Sin `tipo_operacion` | 70,4% | **74,6%** | 67,9% — *sin moverse* |
| Sin Mercado Pago | 66,1% | **67,9%** | 53,6% — *sin moverse* |
| Los 6 de la conciliación | 82,3% | **87,5%** | 76,0% — *sin moverse* |
| Global | 66,0% | **69,9%** | 69,5% — *sin moverse* |

**El base no cambió un solo campo en ningún corte.** Era exactamente lo predicho: perdía 0 por
separadores. Todo el movimiento es el LoRA recuperando lo que se le cobraba por puntuación.
Con esto el LoRA gana también en el global, aun arrastrando `tipo_operacion` en 0/16.

---

## 2. Los 16 apartados dejaron de sortearse

`reales.py` sorteaba con semilla fija **sobre el conjunto de revisados**. Al pasar de 51 a 58
revisados, los 16 habrían sido otros y ningún número publicado volvería a ser comparable.

Ahora son una constante `APARTADOS` con los 16 nombres, y el script **aborta** si falta alguno
entre los revisados. Todo lo que no está apartado entrena, así que sumar comprobantes solo
agranda el entrenamiento. Se sacó `--n-test`, que ya no hacía nada.

---

## 3. Siete comprobantes reales nuevos — 51 → 58

Flujo usado, sin escribir una línea de código: buzón `ia/nuevos/` → verificación de duplicados
**por hash** (0 repetidos contra los 51 en disco y contra los 71 de la base) → copia a
`ia/comprobantes/` como `053`–`059` → `extraer.py` con `--adaptador ia/checkpoints/lora_v3`
→ `pnpm importar:comprobantes` con `--base` → corrección en `/revisar`.

- La extracción de los 7 tardó **menos de 100 s en total**, no los 4-7 min estimados.
- Precarga: 11,6 de 16 campos con valor (mínimo 8, máximo 16). Ninguna colapsada.
- Corrida `lora_v3_nuevos`, separada para no ensuciar mediciones viejas.
- El usuario los revisó los 7. **0 usos de "Guardar igual"** y la forma sigue sana: 0 CUIT y
  0 CBU fuera de forma en los 58.

**Se eligió este camino por sobre arreglar la carga manual de `/comprobante`.** El argumento que
decidió: un comprobante cargado a mano deja la etiqueta pero **no deja ninguna medición**; uno
que pasa por la IA deja etiqueta *y* un dato de cuánto acertó el modelo en ese banco. Los 4
cortes de `/comprobante` (sesión 12 §5) siguen sin arreglar, a propósito.

⚠️ **No se miró ninguna imagen ni se imprimió el JSONL.** Abrir un comprobante real lo mandaría
a un modelo en la nube, que es lo que prohíbe la regla 2. Por eso el adaptador se eligió a
ciegas y se le preguntó al usuario de qué banco eran.

---

## 4. Las imágenes gigantes — lo resolvió el usuario, mejor que la propuesta

Al ir a regenerar el dataset aparecieron dos bloqueantes que no estaban en el plan:

1. Los 300 sintéticos puros (`train.jsonl`) tienen el vocabulario **viejo**
   (`transferencia_saliente` en las 300). El alineado vive solo dentro de `train_v3.jsonl`,
   porque se arregló editando ese archivo y no regenerando.
2. `reales.py` volvía a meter `015.jpeg` y `033.jpeg`, los que **matan el proceso sin dejar
   traceback**. La exclusión vivía a mano en `train_v2_sin_gigantes.jsonl`.

Se propuso excluir por umbral de píxeles. **El usuario hizo algo mejor**: `reales.py` ahora
mide los tokens de cada imagen y **achica una copia** a `ia/comprobantes_reducidos/` cuando pasa
`TOPE_TOKENS = 1800`. No pierde comprobantes, el original nunca se toca, y los 16 apartados se
entregan siempre en tamaño original para no mover la vara en silencio.

**El entrenamiento quedó en pausa** por decisión del usuario: no tiene tiempo ni puede dejar la
Mac enchufada. El dataset no se regeneró.

---

## 5. `/encontrar`: de diagnóstico a herramienta

### La tabla `eleccion` (migración 008) — temporal a propósito

El usuario pidió una tabla que relacione comprobante ↔ fila del extracto con un campo de quién
lo decidió. Se le mostró que `conciliacion.decidido_por` ya es eso, pero se eligió una tabla
aparte porque `/encontrar` **no usa `motor.ts`** —aquél cruza por `cuenta.cbu`, en NULL en las
tres cuentas— y mezclar dos algoritmos en la misma tabla haría imposible saber cuál produjo
cada fila.

Guarda **solo la elección humana**, cuatro columnas. Lo que propone el algoritmo no se guarda:
es determinístico y se recalcula, y congelarlo haría que la fila vieja siguiera afirmando lo
que la regla decía antes. La tasa de corrección sale de cruzar la tabla con la query en vivo.

⚠️ Se borra con un `DROP TABLE` cuando `motor.ts` absorba la cascada.

### Las dos pantallas

- **`/encontrar`** quedó como índice: contadores, un botón *Resolver los N pendientes*, y una
  tabla que solo muestra el estado. Los botones y la info repetida salieron.
- **`/encontrar/[id]`** es la que resuelve, con el layout de `/revisar`: imagen a la izquierda
  (fija al hacer scroll) con los datos del comprobante debajo, y a la derecha los candidatos
  con hoja, fila del Excel, fecha, importe, **detalle**, nro y CUIT. Lo que coincide se pinta
  en verde. Botón *Es esta* y navegación anterior/siguiente.
- **Buscador** por detalle, monto y fecha, combinables, con `<form method="get">` sin
  JavaScript. Sin filtros muestra los movimientos **más cercanos en fecha**, limitado a 50 y
  diciendo cuántos hay en total. El monto pasa por `parsearImporte`, así que `4.800,50` y
  `4800.50` encuentran lo mismo.
- Si un comprobante ya está resuelto, **el buscador no aparece**: ofrecer 50 filas más sería
  empujar a dudar de algo que está bien.

### Tres cosas que se arreglaron sobre la marcha

- La cascada estaba por quedar escrita en dos pantallas. Vive solo en `lib/eleccion.ts`.
- Una fila elegida **a mano** (no candidata) no se recordaba: la pantalla volvía a mostrar el
  buscador. Se relee por id.
- El `volverA` de las Server Actions se valida contra `/^\/encontrar(\/\d+)?$/`: viene del
  formulario y redirigir a donde diga sin mirarlo es cómo se arma un redirect abierto.

---

## 6. 🔴 El hallazgo grande: el CUIT no cruzaba por los guiones

El usuario recorrió los comprobantes y anotó 23 casos con el mismo síntoma: *"el CUIT está en
la descripción y no se identificó"*, *"tenía el CUIT pero pusiste 50%"*.

Tenía razón en todos. La causa, medida:

| | |
|---|---|
| `movimiento.cuit_emisor` | **0** con guiones, 2586 sin |
| `comprobante.cuit_emisor` | **33 con guiones**, 9 sin |
| Cruce por CUIT tal cual | **8** comprobantes |
| Cruce por CUIT **solo por dígitos** | **40** comprobantes |

**Los 33 comprobantes donde una persona escribió el CUIT con guiones no podían cruzar nunca.**
Es el mismo problema de la §1, en otro lugar del código y sin que nadie lo conectara.

Segundo hallazgo: **el `nro_transaccion` casi nunca coincide con la referencia del
comprobante.** Arreglando el CUIT, el escalón 1 sigue dando 4. No es el camino.

### La cascada quedó en tres escalones

```
1. nro de transacción + CUIT     → 90%      (4)
2. CUIT + monto + fecha          → 90%     (23)   ← nuevo
3. monto + fecha                 → 50%      (7)
```

El escalón 2 son **tres datos independientes** coincidiendo: vale lo mismo que el 1. Sin él,
23 comprobantes con los tres datos idénticos quedaban en 50% o sin encontrar.

| Sobre los 58 reales | Antes | Después |
|---|---|---|
| Al 90% | 4 | **26** |
| Ambiguos | 9 | **3** |
| Sin encontrar | 24 | 24 |

**21 de los 23 que anotó el usuario pasaron a 90%.** El CUIT además desempata: era su
observación sobre los comprobantes 23 y 30.

Se midió y se **descartó** un escalón `CUIT + monto` sin fecha: alcanza 37 comprobantes pero
solo 23 con candidato único — metería 14 ambiguos nuevos.

Hay un test que fija que **ignorar guiones NO junta dos CUIT distintos** (el caso del
comprobante 126), para que el arreglo no se convierta en falsos positivos.

---

## 7. La medición contra las elecciones humanas

El usuario eligió 37 filas a mano y pidió saber cuántas coinciden con el algoritmo.

| | | |
|---|---|---|
| ✅ Misma fila, candidato único | 29 | 78,4% |
| 🟡 La suya estaba entre varias | 2 | 5,4% |
| ❌ Habría elegido otra | 1 | 2,7% |
| ⚪ No habría propuesto nada | 5 | 13,5% |

**Cuando el algoritmo decide solo: 29 de 30 → 96,7%** (regla 90%: 25/26 · regla 50%: 4/4).

### Pero el 78,4% está castigado por seis elecciones que no se sostienen

- **`023.jpeg`**, el único "error": la fila que eligió el usuario coincide en monto y fecha pero
  **el CUIT es distinto**; la que propone la regla coincide en los tres. Es justo el comprobante
  del que él escribió *"tenía duda entre 2 pero uno tenía el CUIT"* — eligió el que no lo tiene,
  casi seguro antes de este arreglo. **El algoritmo tiene razón.**
- **De las 5 que encontró a mano, 4 no se sostienen:**

| | CUIT | Monto | Fecha |
|---|---|---|---|
| `007.jpeg` | coincide | **distinto** | coincide |
| `015.jpeg` | **distinto** | coincide | **1166 días** |
| `032.jpeg` | coincide | coincide | **1151 días** |
| `043.jpeg` | **distinto** | coincide | **1096 días** |
| `051.jpeg` | **distinto** | coincide | **−118 días** |

Coincidencia de importe, no la misma transferencia. **Sobre las 31 elecciones que resisten un
chequeo, el algoritmo coincide en 31 de 31.**

`007.jpeg` es el único que vale mirar: CUIT y fecha coinciden y solo cambia el monto — puede ser
un monto mal leído por la IA.

> **Dato del usuario que cierra el tema de los 24 sin encontrar:** *"son comprobantes reales
> para el entrenamiento pero no de este Excel."* Entonces no hay nada roto ahí, y **la ventana
> de fecha ±3 días quedó descartada**: agregaría coincidencias de monto sobre comprobantes que
> ni siquiera pertenecen a este extracto.

---

## 8. Estado al cerrar

```
200/200 tests  ·  tsc limpio (salvo 2 errores PREEXISTENTES en comparar-lora.ts)
migración 008 aplicada en conciliador y conciliador_test
58 comprobantes reales revisados  ·  37 elecciones humanas guardadas
```

**Archivos nuevos:** `migraciones/008_eleccion.sql`, `src/lib/eleccion.ts` (+ su test),
`src/app/encontrar/[id]/page.tsx`, `ia/nuevos/` (buzón vacío), `ia/comprobantes_reducidos/`.
**Tocados:** `lib/importar-comprobantes.ts` (+`SOLO_DIGITOS`), `app/acciones.ts`,
`app/encontrar/page.tsx`, `ia/reales.py`, `.gitignore`.

**Lo que NO se hizo:** regenerar el dataset, `lora_v4`, los 4 cortes de `/comprobante`, y
mostrar por qué falló cada no-encontrado (quedó sin sentido tras el dato del §7).
