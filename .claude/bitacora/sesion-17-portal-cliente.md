# Sesión 17 — Arranca el producto: el portal del cliente

**Fecha:** 2026-08-15 (misma jornada que la sesión 16, después de cerrar la medición)

Se cerró el entrenamiento y empezó la funcionalidad real. Esta sesión construyó **la parte 1 de
2**: el portal del cliente. La parte 2 —el portal del dueño— queda especificada en §5 y **no se
escribió una línea de ella**.

---

## 1. Las seis decisiones de diseño, con su porqué

Todas salieron de preguntas al usuario, una por vez. Ninguna se supuso.

| Decisión | Qué se eligió | Qué se descartó y por qué |
|---|---|---|
| **Base de datos** | **Base nueva `portal`, app aparte.** `web/` y `conciliador` intactos | Se descartó meter tablas nuevas en `conciliador` (dos dueños del esquema: migraciones `.sql` de `web/` + SQLAlchemy) y se descartó que el portal reemplace a `web/` ya mismo |
| **Qué es el saldo** | **Saldo a favor (crédito).** Un comprobante confirmado SUMA; lo que el dueño carga RESTA | Se descartó "saldo = deuda" y la cuenta corriente con signo sin semántica |
| **Acceso** | **Selector de cliente, sin contraseña.** El id va en la URL, no hay sesión | Se descartó usuario+contraseña (maquinaria para una máquina local) |
| **Stack de la UI** | **FastAPI + Jinja2**, todo Python, HTML del servidor | Se descartó un Next.js aparte hablando JSON: dos procesos, dos lenguajes, CORS |
| **Alcance de la parte 1** | **Subir y ver, sin IA.** El comprobante queda `pendiente` | Se descartó extraer al subir (30 s de espera, y le saca sentido al relectura ×3 del lote) |
| **Formulario de subida** | **Solo la imagen** + un campo **opcional** de fecha de la transferencia | Pedido textual del usuario: *"si no está la fecha del comprobante, es decir el día que se realizó, por favor de poner acá"* |

### El saldo va en una columna, no se calcula

Propuse calcularlo (`SUM` del libro) para que no pueda mentir. **El usuario decidió lo
contrario**, con este argumento: *"si hay muchas transacciones, una por día por ejemplo, a los
años se puede hacer demasiado complicada de calcular si se cambia siempre."*

Se hizo como pidió, con dos guardas que hacen que la denormalización sea segura:

1. **`registrar_movimiento()` es el único camino** para mover el saldo, y escribe el movimiento y
   la columna **en la misma transacción**.
2. **`verificar_saldos.py`** recalcula la suma y lista fila por fila. Sale con código 1 si alguna
   no coincide, así puede correr desatendido.

---

## 2. El bug que encontró el verificador a los diez minutos

Escribí el verificador *antes* de confiar en la columna, y en la primera corrida **ninguno de los
seis saldos coincidía**:

```
 id |  columna   | suma_del_libro | coincide
  1 |  -30000.00 |      -67000.00 | f
  2 |  117000.00 |       99000.00 | f
  ...  (6 de 6 mal)
```

**Causa:** `cliente.saldo = Cliente.saldo + monto` produce una **expresión SQL**, no un número.
Si se asigna varias veces sin `flush()` entre medio, cada asignación **reemplaza** a la anterior
en memoria y al final se emite un solo `UPDATE saldo = saldo + <último monto>`. Los otros
movimientos se guardaban en el libro pero no tocaban el saldo.

**Antes de eso hubo un segundo error, del mismo pariente:** en un cliente recién creado, esa
misma expresión se cuela dentro del `INSERT`, y Postgres rechaza que la fila se referencie a sí
misma (`invalid reference to FROM-clause entry for table "cliente"`).

**Arreglo:** dos `flush()` en `registrar_movimiento()`, cada uno tapando uno de los dos casos, con
el porqué escrito al lado en el código. Después: 6/6 coinciden.

> **La lección, que es la misma de siempre en este proyecto:** el verificador no fue una
> formalidad al final, fue lo que encontró el error. Una columna denormalizada sin un chequeo que
> la contradiga es una cifra en la que nadie puede confiar.

---

## 3. Qué se construyó

```
portal/
  db.py                 engine + Sesion. 13 líneas, sin capa de nada
  modelos.py            Cliente · Comprobante · MovimientoCuenta + registrar_movimiento()
  archivos.py           valida, convierte PDF→JPEG, y el nombre lo pone el SERVIDOR
  app.py                las 5 rutas + los filtros `pesos` y `dia` de Jinja
  sembrar.py            6 clientes inventados con 4-9 movimientos cada uno (semilla 2026)
  verificar_saldos.py   recalcula el libro y avisa si el saldo se despegó
  plantillas/           base · elegir · cuenta · subir
  estaticos/estilo.css
  tests/test_portal.py  6 tests con `unittest` (stdlib, sin framework)
  comprobantes/         lo que sube la gente  ← en .gitignore
```

**Las 5 rutas:** `/` elegir cuenta · `/cliente/{id}` saldo + actividad + comprobantes ·
`/cliente/{id}/subir` (GET y POST) · `/cliente/{id}/comprobante/{cid}` sirve la imagen.

### Las tres tablas

```
cliente             id · nombre · apellido · email · cuit · saldo NUMERIC(14,2) · creado_en
comprobante         id · cliente_id · archivo · fecha_declarada(NULL) · estado · subido_en
movimiento_cuenta   id · cliente_id · fecha · concepto · monto(con signo) · comprobante_id(NULL)
```

`estado` es **texto plano, no un `ENUM` de Postgres** — alterar un enum es un dolor y esa lista se
va a mover en la parte 2. Los cuatro valores están declarados como constantes en `modelos.py`:
`pendiente` · `confirmado` · `revision_manual` · `en_disputa`. **La parte 1 solo escribe
`pendiente`**; los otros tres los produce el lote del dueño.

### Decisiones chicas que ahorran dolor después

- **PDF sin dependencia nueva.** El cliente puede subir PDF y sale JPEG hacia adentro, porque
  `extraer.py` lee imágenes. Se usa `pdftoppm` (poppler), **que ya estaba instalado con
  Homebrew** — no se sumó PyMuPDF. Marcado con un comentario `ponytail:` que dice cómo subir el
  techo si el binario desaparece.
- **El nombre del archivo lo pone el servidor** (`{cliente_id}/{uuid}.jpg`). Un nombre venido de
  afuera es la vía clásica para escribir fuera de la carpeta.
- **La extensión no se cree.** Pillow abre el contenido de verdad antes de guardar; un `.jpg` con
  basura adentro se rechaza en vez de quedar esperando a romper la parte 2.
- **Se guarda el archivo primero y la fila después.** Al revés queda una fila apuntando a un
  archivo que no existe.
- **Tres dependencias nuevas y nada más:** `sqlalchemy` 2.0.52, `psycopg` 3.3.4,
  `python-multipart` 0.0.32 (este lo exige FastAPI para recibir archivos; sin él el upload falla
  con un error confuso). Se reusó `ia/.venv`, que ya tenía FastAPI, Jinja2, uvicorn y Pillow.

---

## 4. Lo verificado, con su salida

| Qué | Resultado |
|---|---|
| `unittest discover portal/tests` | **6/6 OK** |
| `verificar_saldos` sobre la base real | **6/6 coinciden** con su libro |
| Subir JPG y PDF | `303` — el PDF quedó como `.jpg` de 38 KB |
| Subir un `.jpg` con basura adentro | `400`, *"El archivo no se pudo abrir como imagen"*, y **0 filas** en la base |
| `/cliente/999` | `404` |
| Comprobante del cliente 2 pedido como cliente 3 | **404** |

Los tests **se niegan a correr** si `PORTAL_DATABASE_URL` no termina en `portal_test`: cotejan la
URL al importar y abortan. Es el mismo criterio que en `web/`, donde el `DATABASE_URL` de test
está a la vista en `package.json`.

Las imágenes de prueba son **fabricadas con Pillow**, nunca comprobantes reales (regla 2).

---

## 5. ⏭️ LA PARTE 2 — el portal del dueño, dictado por el usuario

**Esto no está construido.** Es la especificación tal como la dio el usuario, y manda sobre la
próxima sesión.

### Qué ve y qué hace el dueño

- Carga **el Excel de su banco** (el extracto) y ve **cómo va el negocio**: el análisis entero.
- Ve **todos los clientes**, y puede **cargarles deuda** o **recargarles el saldo** a mano.
- Tiene la bandeja de lo que el lote no pudo resolver.

### El lote: una vez por día, o cuando el dueño aprieta el botón

1. Se traen **todos los comprobantes `pendiente`** de la base.
2. Se leen con la IA — **siempre con el adaptador `lora_v4_v2`**, que es el mejor medido (82,6%).
3. Se compara lo extraído contra el Excel del banco.
4. **Si no aparece la transacción → se asume que se leyó mal y se relee. Hasta 3 veces.**
5. Si después de las 3 sigue sin aparecer **y la fecha salió igual en las tres extracciones**, se
   da la fecha por bien leída. Entonces se mira si en el Excel hay transacciones **de ese día**:
   - **Sí las hay** → el comprobante se marca **no legible** y va a la bandeja del dueño, para que
     lo lea a ojo y decida si estaba bien o mal leído.
   - **No las hay** (ese día todavía no está en el extracto) → queda **`pendiente`** y se reintenta
     en la corrida siguiente.
6. **Si la transacción aparece y se reconoce:** se marca **la fila del Excel como encontrada**,
   para que ningún otro comprobante pueda reclamarla, y se **suma el monto al saldo del cliente**.
7. **Si un comprobante reclama una fila que ya tomó otro → queda en manos del dueño** elegir de
   quién es. (Es el estado `en_disputa`.)

### La verificación del CBU propio — misma mecánica

Además del cruce contra el Excel, se verifica que el **CBU/CUIT del receptor sea uno propio del
dueño**. Si se leyó mal o no figura en la lista, **se relee 3 veces**; si las tres dan lo mismo y
sigue sin estar, **no se rechaza: se le pregunta al dueño si es un CBU suyo nuevo**.

⇒ Hace falta una **tabla de CBU propios** en la base `portal` y una pantalla para aprobarlos.
En `web/` esto ya existe (`/cbu`, migración 006) y sirve como referencia de diseño, **no se
importa**: son bases distintas.

### Lo que hay que decidir antes de escribir la parte 2

- **De dónde sale el extracto en la base `portal`.** El parser del Excel hoy es TypeScript
  (`web/src/lib/extracto.ts`) y sabe cosas caras de aprender: los **dos formatos de número
  mezclados** en la misma columna, el ID COELSA presente solo en el 3% de las filas, la huella
  de la fila. Portarlo a Python es trabajo real y **es donde más fácil se introduce un error
  silencioso**. Hay que decidir: se porta, o el portal lee el Excel de otra manera.
- **Qué significa "las transacciones de ese día están en el Excel"**: ¿alguna fila con esa fecha,
  o el extracto cubre ese día como período? No es lo mismo un día sin movimientos que un día
  fuera del extracto.
- **Cómo se marca una fila como tomada** sin perder que el extracto se puede reimportar (en
  `web/` reimportar es seguro y se apoya en la huella de la fila).

---

## 6. Qué quedó sin hacer

- **Sin commitear.** Todo `portal/`, más `.claude/CLAUDE.md`, `.claude/BITACORA.md`, este archivo
  y la línea de `.gitignore`. Se suma a la deuda de la sesión 16, que también sigue abierta.
- **En la cuenta de Aníbal Ferreyra (id 2) hay 2 comprobantes de prueba**, fabricados durante la
  verificación. Se van con `python -m portal.sembrar --reiniciar`.
- **Sin Alembic.** Las tablas se crean con `create_all()` sobre una base vacía. Mientras los
  datos sean inventados, un cambio de esquema se resuelve con `--reiniciar`. **El día que haya un
  solo dato real de un cliente, esto deja de alcanzar** y hay que meter migraciones.
- **El `.gitignore` cubre `portal/comprobantes/`**, agregado en esta sesión.
