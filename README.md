# Conciliador de Comprobantes Bancarios

Un sistema que revisa si las transferencias que los clientes **dicen** haber hecho
**realmente** entraron al banco.

## El problema

Cuando un cliente paga por transferencia, manda una foto del comprobante. Hasta ahora alguien
tenía que abrir el extracto del banco y buscar a mano si esa plata había entrado. Es lento, y
se escapan dos cosas:

- **Comprobantes falsos:** una captura editada, o un comprobante viejo reenviado.
- **Pagos reales que se pierden:** la plata entró, pero nadie la asoció al cliente.

## La idea

```
  Foto del comprobante  ──►  la IA lee los datos  ──┐
                                                    ├──►  ¿coinciden?  ──►  veredicto
  Extracto del banco (Excel)  ──────────────────────┘
```

La regla de oro: **el extracto del banco es la única verdad.** El comprobante es lo que el
cliente afirma; el extracto es lo que pasó.

Además, el sistema **nunca acusa sin pruebas**. Si un comprobante no aparece en el extracto,
no lo marca como falso enseguida. Primero se fija si tenía forma de verlo: tal vez la plata
fue a otra cuenta o el extracto de ese día todavía no se cargó.

Todo corre en una sola computadora (una MacBook). Los datos bancarios no salen nunca a
internet y no se paga ningún servicio externo.

---

## Tecnologías que usamos

| Tecnología | Qué es | Para qué la usamos |
|---|---|---|
| **Python** | Lenguaje de programación | Escribir el portal y todo lo de inteligencia artificial |
| **FastAPI** | Herramienta de Python para hacer páginas web | Armar el portal donde entran el cliente y el dueño |
| **Jinja2** | Plantillas de HTML | Dibujar las pantallas del portal |
| **SQLAlchemy** (un *ORM*) | Un ORM traduce las tablas de la base de datos a objetos de Python: en vez de escribir `SELECT * FROM cliente`, el código pide un `Cliente` y lo recibe listo para usar | Todo lo que el portal lee y guarda. Las tablas están definidas en `portal/modelos.py` |
| **PostgreSQL** | Base de datos | Guardar clientes, comprobantes, saldos y el extracto |
| **Qwen2-VL** | Modelo de IA que entiende imágenes | Leer la foto del comprobante y sacar monto, fecha, CBU, etc. |
| **MLX** | Herramienta de Apple para correr IA | Hacer andar el modelo en la Mac, sin internet |
| **LoRA** | Técnica de entrenamiento | Enseñarle al modelo a leer *nuestros* comprobantes, ajustando solo una parte chica de él |
| **Next.js + TypeScript** | Herramienta para páginas web | La herramienta interna con la que se entrenó y midió la IA |
| **Looker Studio** | Tableros de Google | Mostrar en gráficos cuánto acierta la IA (con datos sin información bancaria) |

---

## Las tablas de la base de datos

El producto guarda todo en estas tablas:

| Tabla | Qué guarda |
|---|---|
| `cliente` | Cada cliente: nombre, CUIT y su saldo actual |
| `comprobante` | Cada foto o PDF que sube un cliente, y en qué estado está |
| `movimiento_cuenta` | La "libreta" de cada cliente: cada pago, deuda o recarga que movió su saldo |
| `movimiento_banco` | Cada fila del extracto del banco, y qué comprobante se quedó con ella |
| `carga_extracto` | Cada Excel del banco que se subió, para poder deshacerlo |
| `cbu_propio` | Las cuentas bancarias del dueño (para chequear que la plata fue a una cuenta nuestra) |
| `extraccion` | Lo que leyó la IA en cada intento |
| `correccion` | Lo que la IA leyó mal y cuál era el dato correcto. Sirve para volver a entrenarla |

Hay una regla importante: **una fila del banco solo puede pertenecer a un comprobante.** Así
nadie puede cobrar dos veces la misma transferencia. → Detalle completo en
[docs/base-de-datos.md](docs/base-de-datos.md).

---

## Qué hicimos, paso a paso

1. **Miramos los datos reales.** Un extracto de 2822 movimientos y comprobantes de varios
   bancos. Apareció de todo: números escritos en dos formatos distintos en la misma columna,
   y un pago legítimo que no estaba en el extracto porque había ido a otra cuenta.
2. **Diseñamos la base de datos** y los estados posibles de un comprobante (ver abajo).
3. **Programamos el cruce:** la regla que decide si un comprobante coincide con una fila del
   banco (por número de operación, y si no, por fecha y monto).
4. **Probamos la IA tal cual viene** para leer los comprobantes. Acertaba alrededor del 66%
   de los datos.
5. **La entrenamos con LoRA.** Generamos comprobantes de práctica (inventados, sin datos
   reales) y la entrenamos en la Mac. Algunas corridas fallaron y aprendimos de cada una.
6. **La medimos con cuidado:** 16 comprobantes que la IA nunca vio en el entrenamiento, 16
   datos cada uno. El mejor modelo llegó al **82,6%** de los datos, y al **~91%** en los 6
   que deciden si el pago se acredita. → [docs/inteligencia-artificial.md](docs/inteligencia-artificial.md)
7. **Construimos el portal**, el producto final: los clientes suben sus comprobantes y el
   dueño los verifica con un botón. → [docs/portal.md](docs/portal.md)
8. **Armamos un tablero en Looker Studio** con los resultados del entrenamiento.
   → [metricas/LEEME.md](metricas/LEEME.md)

Todo lo que se pudo probar automáticamente tiene tests: **94 en el portal y 200 en la
herramienta de medición**, todos pasando.

---

## Los estados de un comprobante

| Estado | Qué quiere decir |
|---|---|
| **Pendiente** | Se subió y todavía no se revisó |
| **Confirmado** | Se encontró en el extracto. La plata entró y se sumó al saldo del cliente |
| **En disputa** | Otro comprobante ya reclamó esa misma transferencia. Decide el dueño |
| **Revisión manual** | El sistema no puede decidir solo (varias filas posibles, o no aparece). Decide el dueño |

---

## Cómo usarlo

### 1. Prenderlo

Hacen falta dos cosas: la base de datos y el portal.

1. Abrir la aplicación **Postgres** en la Mac (no arranca sola).
2. En la terminal, dentro de la carpeta del proyecto:

   ```bash
   ia/.venv/bin/uvicorn portal.app:app --port 8000
   ```

3. Abrir en el navegador **http://localhost:8000**

### 2. Como cliente

1. En la página principal, **elegir tu nombre** de la lista (no hay contraseña).
2. Vas a ver tu **saldo** y tu **actividad**.
3. Tocar **Subir un comprobante** y elegir la foto o el PDF de la transferencia. La fecha es
   opcional.
4. El comprobante queda **pendiente** hasta que el dueño lo verifique.

### 3. Como dueño (entrar a http://localhost:8000/admin)

1. **Cargar las cuentas propias** en *CBU* (una sola vez). Sin esto el sistema no
   verifica nada, a propósito: no puede saber si la plata fue a una cuenta nuestra.
2. **Subir el extracto del banco** (el Excel) en *Extracto*, eligiendo de qué cuenta es.
3. Ir a *Lote* y **apretar el botón**. La IA lee cada comprobante pendiente, lo cruza con el
   extracto y acredita los que coinciden. Se ve el progreso en vivo.
4. Revisar la **Bandeja**: ahí quedan los casos que el sistema no pudo decidir solo. Cada uno
   muestra la foto, lo que leyó la IA y por qué no lo resolvió. Se corrige y se elige la fila
   correcta.
5. Opcional: **bajar el Excel conciliado** desde el *Tablero* (*Bajar el extracto conciliado*), con el comprobante al lado de cada
   fila del banco.

Los comandos completos (tests, importar por consola, la herramienta de medición) están en
[docs/como-se-corre.md](docs/como-se-corre.md).

---

## Las pantallas del portal

Todas en http://localhost:8000

| Quién | Dirección | Qué se hace ahí |
|---|---|---|
| Cliente | `/` | Elegir tu cuenta |
| | `/cliente/{id}` | Ver saldo y actividad |
| | `/cliente/{id}/subir` | Subir un comprobante |
| | `/cliente/{id}/comprobante/{id}` | Ver un comprobante subido |
| Dueño | `/admin` | Tablero |
| | `/admin/cbu` | Cargar las cuentas bancarias propias |
| | `/admin/extracto` | Subir el Excel del banco (y deshacer una carga) |
| | `/admin/lote` | Leer, cruzar y acreditar con un botón |
| | `/admin/bandeja` | Resolver los casos dudosos |
| | `/admin/comprobantes` | Todos los comprobantes subidos |
| | `/admin/clientes` · `/admin/cliente/{id}` | Los clientes, y cargar a mano una deuda o una recarga |
| | `/admin/exportar` | Bajar el extracto conciliado |

---

## Las carpetas

| Carpeta | Qué hay |
|---|---|
| `portal/` | **El producto:** el portal del cliente y el panel del dueño |
| `ia/` | La inteligencia artificial: lectura de comprobantes y entrenamiento |
| `web/` | La herramienta interna con la que se entrenó y midió la IA |
| `metricas/` | Los datos del tablero de Looker Studio |
| `docs/` | Las explicaciones en detalle |
