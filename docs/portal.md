# El portal (el producto)

> Para saber más. El problema, los estados de un comprobante con su porqué, el recorrido completo dentro del portal, sus pantallas y lo que falta. La versión corta está en el [README](../README.md).

## ⚠️ Hay DOS aplicaciones y no se mezclan

| Carpeta | Qué es | Stack | Base | Estado |
|---|---|---|---|---|
| **`portal/`** | **El producto.** Portal del cliente y panel del dueño | FastAPI + Jinja2 + SQLAlchemy | `portal` | en construcción |
| `web/` | La herramienta con la que se **entrenó y midió** la IA | Next.js 16 + TS + `pg` plano | `conciliador` | terminada, congelada |

`ia/` sirve a las dos.

**`web/` no se toca ni se migra.** Es la evidencia de cómo se midieron los cinco adaptadores
y de dónde salió la verdad de referencia; el día que se apague, los números dejan de ser
reproducibles. Todo lo que sigue **hasta la sección `# El producto` describe `web/`**; de ahí
en adelante, `portal/`.

---

## El problema

Cuando un cliente paga por transferencia, manda una captura del comprobante por WhatsApp.
Hoy esa captura se revisa **a mano**: alguien abre el extracto del banco y busca si esa
transferencia realmente entró. Con ~10-20 comprobantes por día y tres cuentas bancarias,
es lento y se escapan cosas.

Dos riesgos concretos:

1. **Comprobante falso.** Una captura editada, o el comprobante de otro pago reenviado como
   si fuera nuevo. El dinero nunca entró.
2. **Pago real que se pierde.** Entró la plata pero nadie la asoció al cliente, y se le
   sigue reclamando una deuda que ya pagó.

## Qué hace el sistema

Cruza dos fuentes y dice cuáles coinciden:

```
  Comprobantes (imágenes)  ─┐
                            ├──►  Motor de conciliación  ──►  Estado por comprobante
  Extracto del banco (Excel)┘                                 Estado por movimiento
```

La **única fuente de verdad es el extracto del banco.** El comprobante es lo que el cliente
afirma; el extracto es lo que pasó. Un comprobante vale exactamente lo que su fila en el
extracto lo respalde.

## Los estados posibles

Este es el corazón del diseño, y la razón por la que no alcanzan dos estados.

| Estado | Qué significa | Qué hacer |
|---|---|---|
| ✅ **Verificado** | El comprobante tiene su movimiento en el extracto | Nada, la plata entró |
| ❌ **Sospechoso** | La cuenta destino está cargada y el extracto cubre esa fecha, pero el movimiento no existe | Revisar en serio |
| ⚠️ **No verificable** | La cuenta destino no está cargada, o el extracto no cubre esa fecha | **No opinar.** Falta información |
| 🔁 **Duplicado** | Dos comprobantes distintos reclaman el mismo movimiento | Uno de los dos es reenvío |
| ❓ **Ambiguo** | Varios movimientos podrían corresponder al mismo comprobante | Decisión humana |
| 💰 **Sin comprobante** | Entró plata al banco y nadie mandó comprobante | Averiguar de quién es |

### Por qué "No verificable" existe

Es la decisión de diseño más importante del proyecto.

Al analizar un comprobante real de $250.000 se vio que no aparece en ninguno de los 2822
movimientos del extracto. No es falso: fue a una cuenta de Mercado Pago que no está entre
las tres cuentas cargadas.

**"No aparece en el extracto" no significa "es falso".** Significa "no aparece en el extracto".
Si el sistema colapsa esos dos estados en uno, acusa de tramposos a clientes que pagaron bien,
y una sola acusación falsa destruye la confianza en toda la herramienta.

Regla: **el sistema solo dice "sospechoso" cuando puede probar que tenía cómo verlo y no lo vio.**

---

# El producto — `portal/`

Todo lo anterior describe `web/`, la herramienta con la que se entrenó y midió la IA.
**Esta sección describe el producto**, que es una aplicación distinta, con su propia base y
su propio stack: **FastAPI + Jinja2 + SQLAlchemy 2.0, todo Python, base `portal`.**

La diferencia de fondo: en `web/` una persona sube el extracto y revisa comprobantes para
generar datos de entrenamiento. En `portal/` **los clientes suben sus propios comprobantes**,
el dueño aprieta un botón, y el sistema acredita saldo solo.

## Las dos mitades

```
   CLIENTE                                    DUEÑO
   ───────                                    ─────
   ve su saldo                                sube el Excel del banco
   ve su actividad                            aprieta "leer los comprobantes"
   sube comprobantes (foto o PDF)             decide lo que el lote no pudo
                                              carga deudas y recargas
                                              baja el Excel conciliado
```

El cliente entra por `/` y elige su cuenta de una lista. El dueño entra por `/admin`.
**Ninguno de los dos tiene contraseña**, por decisión explícita: corre en una sola máquina.
Esto **no es seguridad** — el único aislamiento real es que cada ruta comprueba que el
recurso pedido sea de quien lo pide. El día que salga de esta máquina hace falta login.

## El modelo de datos — seis tablas

```
cliente             id · nombre · apellido · email · cuit · saldo · creado_en
comprobante         id · cliente_id · archivo · fecha_declarada · estado · intentos ·
                    confianza · motivo · subido_en
movimiento_cuenta   id · cliente_id · fecha · concepto · monto · comprobante_id · creado_en
movimiento_banco    el extracto importado + comprobante_id (la marca de "fila tomada")
carga_extracto      una fila por Excel subido, para poder deshacerlo
cbu_propio          las cuentas del dueño, contra las que se verifica el receptor
extraccion          lo que leyó la IA, por intento. Nunca se pisa
correccion          lo que la IA leyó MAL y lo que era. Combustible de reentrenamiento
```

### El saldo es una columna, no una suma

Decisión del usuario, con este argumento: *"si hay muchas transacciones, una por día por
ejemplo, a los años se puede hacer demasiado complicada de calcular si se cambia siempre."*

La propuesta original era calcularlo (`SUM` del libro) para que no pudiera mentir. Se hizo
como pidió, con dos guardas que hacen la denormalización segura:

1. **`registrar_movimiento()` es el ÚNICO camino** que mueve el saldo, y escribe el
   movimiento y la columna **en la misma transacción**.
2. **`portal/verificar_saldos.py`** recalcula la suma y avisa fila por fila. Sale con código
   1 si alguna no coincide, así puede correr desatendido.

> El verificador encontró un bug en su primera corrida: **los seis saldos estaban mal.**
> Varios `saldo = saldo + monto` pendientes en la misma sesión se pisan en memoria y
> sobrevive solo el último. Por eso `registrar_movimiento()` lleva dos `flush()`, cada uno
> con su porqué escrito al lado. **Correrlo después de tocar cualquier cosa que sume o reste.**

### La fila tomada la garantiza Postgres, no el código

`movimiento_banco.comprobante_id` es **UNIQUE**. Que dos comprobantes no puedan quedarse con
la misma transferencia no es una promesa del lote: un segundo intento **choca contra la
base**, y ese choque *es* la señal de disputa.

## El recorrido de un comprobante

```
  el cliente lo sube            →  pendiente
  el dueño aprieta el botón     →  el lote lo lee hasta 3 veces
       cruza y la fila está libre    →  confirmado       (suma el saldo, toma la fila)
       cruza y la fila ya es de otro →  en_disputa       (elige el dueño)
       cruzan varias filas libres    →  revision_manual  (la regla no adivina)
       no cruza en 3 intentos        →  ver abajo
```

Agotados los tres intentos, y **si la fecha salió igual en los tres**:

- **¿hay alguna fila del extracto de ese día?** → sí: `revision_manual` (el día está cargado
  y la transferencia no aparece) · no: sigue `pendiente` (falta subir ese período).
- **si la fecha cambió entre intentos** → `revision_manual`: no se puede saber de qué día es.

Aparte, el **CBU/CUIT del receptor** se coteja contra `cbu_propio`. Si no figura no se
rechaza: se relee, y si se sostiene en los tres intentos **se le pregunta al dueño si es una
cuenta suya nueva**. Si no hay ningún CBU propio cargado, **el lote se niega a arrancar**:
acreditar sin ese chequeo es sumar saldo por una transferencia que pudo ir a cualquier lado.

### Por qué la imagen cambia en cada intento

**`extraer.py` corre con `temperature=0.0`: es determinista.** Leer la misma imagen tres
veces devuelve tres veces exactamente lo mismo, así que releer sin cambiar nada cuesta el
triple de tiempo y no aporta un solo dato. Por eso cada intento ve una imagen distinta —
`original`, `contraste`, `escala` — que además ataca donde está el techo medido: el LoRA no
toca la parte visual, así que lo que falla es la lectura, no la escritura.

> ⚠️ **Un token cada 28×28 px, y escalan con el ÁREA.** Agrandar el lado 1,5× son 2,25 veces
> más tokens. Medido: una foto de 1320×2782 (≈4.653 tokens) anda; al 1,5× (≈10.430) **mlx
> intenta reservar 57 GB y el proceso muere**. Por eso `TOKENS_MAXIMOS = 4000` se aplica a
> **las tres** variantes, y `escala` va siempre a *otra* resolución que `original`: agranda
> las chicas hasta el tope y achica las grandes a la mitad.

### La cascada del cruce

Es la misma que se midió en `web/` —29 aciertos de 30 cuando propone un solo candidato— y
vive **solo** en `portal/cascada.py`:

```
1. nro de transacción + CUIT     → 90%
2. CUIT + monto + fecha          → 90%
3. monto + fecha (solo ingresos) → 50%   ← solo si el dueño lo habilita al correr el lote
```

Los escalones son **excluyentes** y el CUIT se compara **por sus dígitos** (el extracto no
trae guiones y una persona sí). **La cascada no elige**: si dos filas cruzan igual vuelven
las dos y decide el dueño. El importe que se acredita sale **del extracto**, nunca de lo que
leyó la IA.

## Las diez pantallas

| Ruta | Qué hace |
|---|---|
| `/` | El cliente elige su cuenta |
| `/cliente/{id}` | Su saldo, su actividad y sus comprobantes |
| `/cliente/{id}/subir` | Foto o **PDF** (se convierte a JPEG solo), más una fecha opcional |
| `/admin` | Plata por mes · estado de los comprobantes · clientes por saldo · **filas sin comprobante** |
| `/admin/extracto` | Subir el Excel **eligiendo a qué cuenta va**, ver las cargas anteriores y **deshacerlas** |
| `/admin/lote` | El botón, el umbral (90% o 90+50%) y el progreso en vivo |
| `/admin/bandeja` | Lo que espera una decisión |
| `/admin/bandeja/{id}` | **El diagnóstico de 5 pasos**, corregir los 16 campos y elegir la fila |
| `/admin/comprobantes` | Todos, con filtros por estado, cliente y **por lo que leyó la IA** |
| `/admin/clientes` · `/admin/cliente/{id}` | Cargar deuda o recarga, y deshacer |
| `/admin/cbu` | Las cuentas propias |
| `/admin/exportar` | **El extracto entero a Excel**, con el comprobante de cada fila |

### El diagnóstico — «¿por qué está así?»

Cada comprobante explica su estado en cinco pasos, con ✓ / ✕:

| Paso | Qué dice |
|---|---|
| **Lectura** | cuántas veces se leyó y con qué variantes, o el error si falló |
| **Qué entendió** | monto, fecha, CUIT y referencia — y ⚠️ si **cambiaron entre lecturas** |
| **Receptor** | qué CBU leyó y si está entre las cuentas del dueño |
| **Cruce con el extracto** | cuántas filas coinciden, cuáles están libres y por qué escalón |
| **El día en el extracto** | si hay movimientos de esa fecha cargados |

**Se recalcula cada vez, no se guarda.** Si el dueño carga un CBU o sube más extracto, el
diagnóstico cambia solo, en vez de repetir una frase congelada que ya no es cierta. Y mira
**solo la última corrida**: mezclar dos corridas haría decir "la fecha cambió entre lecturas"
comparando cosas distintas.

### El Excel conciliado

Una fila por movimiento del banco, con tres columnas más y las filas pintadas:

| ¿Encontró comprobante? | Certeza | Archivo del comprobante |
|---|---|---|
| SÍ / NO | 🟢 `90% · nro de transacción o CUIT` · 🟡 `50% · solo monto y fecha` · 🟢 `Elegido por el dueño` · 🔴 `—` | el nombre del archivo |

### Las cargas del extracto

Cada Excel subido queda registrado. Se puede **elegir a qué cuenta van las filas** (o dejar
que cada hoja vaya a la cuenta que lleva su nombre), subir varios archivos sin miedo a
duplicar —la huella deduplica—, y **deshacer una carga equivocada**.

> Deshacer **no borra a ciegas**: primero muestra qué se pierde. Si alguna de esas filas ya
> acreditó plata, cada acreditación se anula con su **contra-movimiento** y el comprobante
> vuelve al lote. Borrar la fila sin más dejaría el saldo de un cliente apoyado en un
> movimiento que ya no existe.

## La tabla de correcciones — la fábrica de datos

Cada campo que el dueño corrige en la bandeja deja una fila en `correccion`:

```
campo · valor_leido · valor_correcto · descripcion · adaptador · variante
```

Se guarda **por campo y no como texto libre**, porque para reentrenar hace falta el par
(imagen, los 16 campos correctos) que consume `ia/reales.py`. Una descripción en prosa no se
puede convertir en un ejemplo de entrenamiento; un `campo · valor_leido · valor_correcto` sí.

**Es lo que destraba el cuello de botella medido del proyecto:** la verdad de referencia son
58 comprobantes corregidos a mano, y no hay forma barata de conseguir más. Cada corrección
del dueño —trabajo que hay que hacer igual— produce un ejemplo nuevo.

⚠️ **Falta el exportador a JSONL.** La tabla guarda lo que hace falta, pero el script que la
convierte al formato de `reales.py` todavía no existe.

## El parser del extracto, portado de TypeScript

`portal/extracto.py` es el porteo de `web/src/lib/extracto.ts`. **Los 34 tests se portaron
primero** y son la vara del porteo. Se portó en vez de llamar al de TS para que el producto
no dependa de `web/`.

**Verificado contra datos reales:** los mismos 2822 movimientos por los dos parsers dan
**cero diferencias** en fecha, importe, ingreso/egreso, CUIT, COELSA, tipo y la marca de
revisión.

> ⛔ La `huella()` de `web/` **no reproduce su propia fórmula documentada**: `shasum`, Node
> inline y Python coinciden entre sí y difieren de ella. No está resuelto. No bloquea nada
> —la huella es una clave interna de deduplicación y cada base es consistente consigo
> misma— pero **las huellas de las dos bases no son comparables**.

## Lo que NO está hecho

- **El lote nunca corrió de punta a punta contra la IA con éxito.** Los tests usan un doble;
  la primera corrida real murió por el bug de los tokens, ya arreglado, pero **no se volvió
  a probar**.
- **Los clientes se crean solo con `sembrar.py`.** No hay alta desde el panel (decidido).
- **El exportador de correcciones a JSONL.**
- **Login.** Ni cliente ni dueño.

---

# Estado del proyecto

```
F0 ✅  F1 ✅  F2 ✅  F3 ✅  F4 ✅  F5 ✅     BLOQUE A — la conciliación
F6 ✅  F7 ✅  F8 ✅  F9 ✅  F10 🟡           BLOQUE B — la IA
F11 ⬜  F12 ⬜                              BLOQUE C
```

**El Bloque A está terminado:** el sistema importa, concilia y se usa a mano. **El Bloque B está
casi cerrado:** hay cinco LoRA entrenados, uno medido al 81,7% contra el 66,1% del modelo base, y
una corrida en curso que corrige los sesgos que la medición destapó.

El plan fase por fase está en **[`.claude/PLAN.md`](../.claude/PLAN.md)**, el estado del día en
**[`.claude/BITACORA.md`](../.claude/BITACORA.md)**, y las reglas de trabajo en
**[`.claude/CLAUDE.md`](../.claude/CLAUDE.md)**.

## Lo que hace falta de una persona

Ninguna de estas cosas la puede resolver el código:

- **Comprobantes reales de bancos nuevos.** No falta cantidad, falta variedad: Mercado Pago ya
  es el 56% de la vara. Cinco comprobantes de cinco bancos distintos valen más que treinta de
  uno solo.
- **Aprobar los CBU propios en `/cbu`.** De 8 candidatos distintos en la verdad, **5 ya están
  aprobados y quedan 3**.
- **Los CUIT de las 3 cuentas.** El extracto trae CUIT en el 98,7% de los ingresos.
- **Un caso real completo** — extracto y comprobantes de la misma fuente y período. Es lo único
  que valida la regla del 90% de punta a punta.
- **Decidir la meta.** El 98% sobre los 16 campos no es alcanzable: el techo lo pone `concepto`,
  que es texto libre. La propuesta es exigirlo **por campo sobre los 6 que deciden la
  conciliación**, que hoy van 91,7%.

---

# Alcance

## Entra en la versión 1

- Importar extractos de Excel a Postgres, sin duplicar, de varias cuentas
- Cargar comprobantes (imagen o PDF) y extraer los 16 campos
- Conciliar y clasificar en los seis estados
- Pantallas para revisar, filtrar y resolver los casos ambiguos a mano
- Historial: qué se verificó, cuándo, y quién decidió los casos dudosos

## Queda para después, en este orden

1. **Conexión con la API de deudas.** Hoy el sistema no manda información a ningún lado: solo
   compara y opina. La deuda vive en otro sistema y se integra al final.
2. **Alta automática de comprobantes** desde la API en vez de subida manual.

## Fuera de alcance, decidido

- **Análisis forense de imagen** (detectar Photoshop, metadatos). El extracto ya dice la verdad;
  el forense agrega complejidad y falsos positivos sin agregar certeza.
- **Multiusuario y permisos.** Uso local, una persona.
- **Deploy en la nube.** Ver la restricción de MLX, y la de los datos.

---

# La carpeta `viejo/`

Intento anterior, no funcional. **No se borra, no se modifica, no se importa.** Se consulta.

El bug que lo mató, documentado porque costó el proyecto entero: el formato `image/prompt/answer`
**no es** el que espera `mlx_vlm.lora` 0.1.15, que quiere `images`/`messages`. Ninguna de esas
tres claves existe para el trainer, así que el entrenamiento nunca corrió.

De ahí sale una de las reglas de trabajo actuales: **se consulta la documentación de la librería
antes de escribir contra ella, aunque uno crea que se acuerda de la API.**

---

