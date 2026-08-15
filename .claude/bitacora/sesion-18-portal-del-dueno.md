# Sesión 18 — El portal del dueño, y tres cosas que rompí

**Fecha:** 2026-08-15 (sigue la 17, misma jornada)

Se construyó **la parte 2**: el panel del dueño entero, el parser del extracto portado a
Python, el lote con su cascada, y las diez pantallas. **94 tests en verde.**

Lo más valioso de esta sesión no son las funcionalidades: son **los tres errores que cometí
y cómo se descubrieron**. Están primero por eso.

---

## 1. 🔴 Borré un comprobante que había subido el usuario

**Qué pasó.** A las 13:16:56 el usuario subió un comprobante al cliente 6. A las 13:38 y a
las 13:47 corrí `sembrar.py --reiniciar` para crear las tablas nuevas del panel. Eso hace
`drop_all`: **se llevó puesta la fila**. El archivo quedó en disco —`--reiniciar` solo toca
la base— así que en la pantalla el comprobante apareció y después desapareció.

El usuario lo reportó como un bug del código. No lo era.

**Cómo se encontró.** Había un archivo en `portal/comprobantes/6/` sin ninguna fila que lo
representara. Los timestamps cerraron la historia: archivo a las 13:16, `--reiniciar` a las
13:38.

**Qué se hizo.**

1. Se reconstruyó la fila desde el archivo del disco.
2. **`--reiniciar` ahora se niega** si hay comprobantes subidos, y explica por qué. Pide
   `--forzar` para insistir.
3. Todos los cambios de esquema posteriores se hicieron con **`ALTER TABLE`**, sin recrear.

> **La lección, que vale más que el arreglo:** en una base sin migraciones, `drop_all` es la
> operación por default para cambiar el esquema, y eso es exactamente lo que la vuelve
> peligrosa el día que hay un solo dato que no se puede regenerar. Los datos inventados se
> rehacen con un comando; lo que subió una persona, no.

## 2. 🔴 El lote se cayó y no dijo absolutamente nada

**Qué pasó.** El usuario corrió el lote. El comprobante quedó en `pendiente`, sin motivo, con
`intentos = 0` y **cero extracciones**. La pantalla decía "el lote no está corriendo".

**La causa raíz, en tres capas:**

| Capa | Qué estaba mal |
|---|---|
| **El disparador** | La variante `escala` agrandaba la imagen 1,5×. Los tokens escalan con el **ÁREA**: 2,25× más. La foto pasó de 4.653 a **10.430 tokens** y mlx intentó reservar **57 GB** |
| **La invisibilidad** | `subprocess.run(check=True)` levantaba la excepción, que moría dentro de `BackgroundTasks`. Nadie la veía nunca |
| **La pérdida** | Todo se guardaba con un solo `commit()` al final. El crash de la tercera variante hizo rollback de **las dos lecturas buenas** |

⚠️ **La bitácora ya advertía sobre los tokens** (*"un token cada 28×28 px, sin resize a
tamaño fijo: escalan con el ÁREA"*, sesión 13) y lo pisé igual.

**Qué se hizo.**

- `TOKENS_MAXIMOS = 4000` aplicado a **las tres** variantes, no solo a la que agranda: una
  foto de celular sola ya se pasa.
- `escala` va siempre a **otra** resolución que `original` — agranda las chicas hasta el tope
  y achica las grandes a la mitad. Si van al mismo tamaño, con `temperature=0.0` las dos
  lecturas son idénticas y la relectura no significa nada.
- `leer()` levanta `FalloDeLectura` con las últimas líneas del stderr adentro; el error queda
  en `ESTADO['error']` (que la pantalla muestra) y en el `motivo` de cada comprobante.
- **`commit()` al cerrar cada vuelta de variante.** Leer cuesta minutos de modelo.
- Si la lectura falla, **no** se corre `_cerrar_sin_cruce`: decir *"no aparece en el
  extracto"* cuando en realidad no se pudo leer sería mentirle al dueño.

**Y de ahí salió el `diagnostico()`**, que es lo que el usuario pidió: cinco pasos con ✓/✕
que explican por qué un comprobante está donde está. Se **recalcula** en cada visita en vez
de guardarse, así refleja el estado de hoy y no una frase congelada.

## 3. 🟡 Los comprobantes salían duplicados en la lista

**Qué pasó.** `/admin/comprobantes` mostraba 5 filas para 3 comprobantes.

**Causa.** La subconsulta buscaba la última lectura por `max(intento)`. Correr el lote dos
veces deja **dos extracciones con `intento = 3`** para el mismo comprobante, así que el join
devolvía dos filas. El comprobante que se leyó una sola vez salía una sola vez — que es la
pista que lo delató.

**Arreglo.** Se busca por `max(id)`, que es único. Y se agregó `ultimas_lecturas()`, que
devuelve **solo el bloque de la última corrida** (desde el último `intento == 1`): mezclar
corridas hacía que el diagnóstico dijera *"la fecha cambió entre lecturas"* comparando
corridas distintas, que es una conclusión falsa.

---

## 4. ✅ El porteo del parser, verificado contra los 2822 reales

`portal/extracto.py` es el porteo de `web/src/lib/extracto.ts`. **Los 34 tests se portaron
primero**, y quedaron 33 (la distinción `null`/`undefined` no existe en Python).

La verificación definitiva salió de un accidente feliz: el usuario importó el extracto real
por la pantalla nueva mientras yo trabajaba, así que quedaron los mismos datos en las dos
bases. Comparados por la coordenada de la fila en el Excel:

```
filas TypeScript: 2822        filas Python: 2822
diferencias en fecha, importe, es_ingreso, cuit, coelsa, tipo, requiere_revision:
  NINGUNA
```

### ⛔ La `huella()` de `web/` no reproduce su propia fórmula

Al intentar cruzar por huella dieron **0 coincidencias de 2822**. La bitácora avisa que eso
*"no es un resultado, es un síntoma"*, así que se persiguió:

| Quién calcula | sha256 de los mismos 5 campos |
|---|---|
| `shasum -a 256` (árbitro) | `651b8a98…` |
| Python (`portal/extracto.py`) | `651b8a98…` |
| Node, inline | `651b8a98…` |
| **`huella()` de `web/src/lib/extracto.ts`** | **`ccfa65ee…`** |

Con los mismos cinco strings pasados a mano. **Sin explicación.** No bloquea nada —cada base
es consistente consigo misma y la huella solo deduplica— pero **las huellas de las dos bases
no son comparables**, y la función de `web/` no hace lo que su propio comentario dice.

---

## 5. Lo que se construyó

```
portal/extracto.py        el parser del banco, portado de TS · 33 tests
portal/importar.py        Excel → base, con cuenta elegible y registro de cargas · 16 tests
portal/cascada.py         los 3 escalones de cruce, lógica pura · 16 tests
portal/lote.py            el recorrido completo, las variantes y el diagnóstico · 21 tests
portal/exportar.py        el extracto conciliado a Excel, con colores
portal/admin.py           las pantallas del dueño
```

Tablas nuevas: `movimiento_banco` · `carga_extracto` · `cbu_propio` · `extraccion` ·
`correccion`, más `comprobante.intentos`, `.confianza` y `.motivo`.

### Las decisiones del usuario en esta sesión

| Pregunta | Respuesta |
|---|---|
| Relectura ×3 con modelo determinista | **variar la imagen** |
| El lote | **en segundo plano con progreso** |
| El extracto | **portar el parser a Python** |
| Acceso del dueño | **sin contraseña, en `/admin`** |
| Umbral de acreditación | **lo elige el admin al correr** (90, o 90+50) |
| ¿Verificar que el comprobante sea del cliente? | **confiar en quién lo subió** |
| Alta de clientes | **solo `sembrar.py`** por ahora |
| Deshacer | **contra-movimiento**, nunca borrar |
| La bandeja | **corregir los campos Y elegir la fila** |
| El perdedor de una disputa | **vuelve a `pendiente`** |
| CBU propios | **pantalla de carga en `/admin`** |
| El tablero | plata por mes · estado de comprobantes · clientes por saldo · **filas sin comprobante** (lo agregó el usuario, y es mejor métrica que la que yo propuse) |

### La tabla de correcciones — idea del usuario

Pidió guardar *"el error y su descripción para luego poder reentrenar"*. Se implementó **por
campo** (`campo · valor_leido · valor_correcto`) y no como texto libre: `ia/reales.py`
necesita los 16 campos con su valor correcto, y una descripción en prosa no se convierte en
un ejemplo de entrenamiento. La nota libre quedó igual, como campo opcional.

**Es la fábrica de datos etiquetados que el proyecto no tenía.** ⚠️ Falta el exportador a
JSONL: la tabla guarda lo que hace falta, pero el script que la convierte no existe.

### Un cambio de criterio, dicho para que se entienda

En la sesión 17 decidí **no** hacer tabla de cargas, con el argumento de que ninguna métrica
del tablero la necesitaba. El pedido de *"ver las cargas viejas y deshacerlas"* la volvió
necesaria y se agregó (`carga_extracto`). El comentario del código que decía lo contrario se
corrigió. **YAGNI acertó en el momento y el requisito cambió después: eso no es un error de
diseño, pero el documento que lo justificaba sí tenía que actualizarse.**

---

## 6. ⏭️ Lo que sigue

1. 🔴 **Correr el lote de punta a punta contra la IA.** Nunca terminó bien: la primera
   corrida real murió por los tokens. Hace falta **cargar los CBU propios de verdad** —el
   único cargado es `0170099220000012345678`, **inventado durante las pruebas y hay que
   borrarlo**— y darle al botón.
2. **El exportador de `correccion` a JSONL**, que es lo que cierra el círculo del
   reentrenamiento.
3. **Commitear.** Nada de las sesiones 16, 17 y 18 está en git.
4. **Podar `BITACORA.md`**, que sigue muy arriba del techo.
