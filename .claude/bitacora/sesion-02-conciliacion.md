<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-06 · Sesión 2 — F1 a F5: la conciliación completa

**Estado al empezar:** F0 cerrado, F1 propuesto sin confirmar. Postgres arriba, base
`conciliador` vacía (`Did not find any tables`).

### Lo que se creó

| Archivo | Qué es |
|---|---|
| `web/migraciones/001_inicial.sql` | Las 5 tablas, el índice único parcial, las 3 cuentas |
| `web/src/lib/db.ts` | 4 líneas: el `Pool` de `pg` leyendo `DATABASE_URL` |
| `web/src/lib/db.test.ts` | Los 2 tests de F1 |
| `web/package.json` | Scripts `db:migrar` y `test` |
| `web/tsconfig.json` | `allowImportingTsExtensions: true` |

### Criterio de listo — cumplido, con la salida pegada

```
$ pnpm db:migrar
BEGIN / CREATE TABLE ×5 / CREATE INDEX / INSERT 0 3 / COMMIT

$ pnpm test
✔ la base rechaza que dos comprobantes reclamen el mismo movimiento (47.8ms)
✔ la base rechaza un movimiento sin importe que no esté marcado para revisar (1.3ms)
ℹ tests 2 · pass 2 · fail 0

$ psql -d conciliador -c '\dt'
comprobante · conciliacion · cuenta · extracto_carga · movimiento   (5 tablas)
cuenta: 1 SUCESION · 2 QUIQUE · 3 MARIELA   (banco, cbu, alias en NULL)
movimiento: 0 filas · conciliacion: 0 filas   (los tests hacen ROLLBACK, no ensucian)

$ pnpm exec tsc --noEmit
sin errores
```

Antes de migrar, el test se corrió en rojo a propósito: falló con
`relation "cuenta" does not exist`. Rojo por el motivo correcto, después verde.

### Decisiones de esta sesión

| Decisión | Motivo |
|---|---|
| Tests con `node --test`, sin vitest ni jest | Node 24 corre TypeScript sin transpilador. Cero dependencias nuevas |
| `movimiento.importe_crudo TEXT NOT NULL` — **columna que no estaba en el `PLAN.md`** | Las 29 filas de importe ambiguo quedan con `importe` NULL. Sin el texto original (`'$ 1.500'`) la persona que revisa no tiene qué mirar |
| `CHECK (importe IS NOT NULL OR requiere_revision)` | Que la base impida un importe fantasma sin marcar, no el código |
| `CHECK ((movimiento_id IS NULL) = (confianza IS NULL))` | Un veredicto que señala un movimiento tiene que decir con qué confianza |
| `'sin_comprobante'` **no** está en el `CHECK` de `conciliacion.estado` | Es estado del movimiento, no del comprobante. Sale de una query (ingresos que ninguna conciliación referencia). No se guarda lo que se puede preguntar |
| Sin índices más allá de las claves y los UNIQUE | 3364 filas: el seq scan es instantáneo. Se agregan en F4 si una query lo pide |
| La migración no lleva `DROP TABLE` | En F2 esta base tiene datos reales. Una migración que borra sola es un accidente esperando |
| `banco` de las 3 cuentas en NULL | El extracto no dice qué banco es. No se inventa |
| `db.ts` sin wrapper ni repositorios | Se exporta el `Pool` y se escribe SQL donde se usa |

### Abierto tras F1

- **`conciliacion` no tiene `UNIQUE(comprobante_id)`.** Falta decidir si un comprobante guarda
  un solo veredicto vigente o el historial completo de veredictos. Lo define F4
- **Falta cómo se anota el `duplicado`.** El índice único impide el segundo `INSERT`, pero no
  hay columna que diga *con cuál* comprobante chocó. Sale una `002_` en F4 si hace falta
- `pnpm test` tira un warning `MODULE_TYPELESS_PACKAGE_JSON`. Es de performance, no rompe nada.
  Se arregla con `"type": "module"` en `web/package.json` — no se tocó por no mover a Next
- `/ponytail-review` no está instalado como comando. La skill `ponytail` sí corrió durante todo
  el código. Sin git no hay diff que revisar de todos modos

### Las 21 filas duplicadas — resuelto mirando los datos

La sesión 1 dejó abierto si las filas repetidas se descartaban o se marcaban. Para decidirlo
había que saber si eran **un pegado duplicado** o **dos transferencias reales** que coinciden
en fecha, importe y descripción. Borrar las segundas sería perder plata que entró.

**La columna que lo distingue es `SALDO`**, que `CLAUDE.md` prohíbe usar. Se pidió permiso
explícito y el usuario lo dio, acotado: **`SALDO` como comparador sí/no, nunca guardado,
nunca mostrado, nunca en el modelo.** La prohibición sigue en pie para todo lo demás.

**El argumento:** si la misma transferencia hubiera entrado dos veces, el saldo después de la
segunda sería `saldo + importe`, distinto del de la primera. En los 21 grupos el saldo quedó
igual y el importe no es cero en ninguno → el saldo se movió una sola vez → un solo
movimiento listado dos veces.

**Antes de creerle al comparador, se lo verificó:**

| Control | Resultado |
|---|---|
| ¿`SALDO` está cargado? | 2843 de 2843 filas. Ninguna vacía |
| ¿Discrimina o se repite siempre? | 2802 valores distintos sobre 2843 filas |
| ¿Algún grupo con importe cero? (rompería el argumento) | 0 de 21 |
| ¿Saldos repetidos fuera de los duplicados? | 20 grupos más, pero difieren en fecha/importe |

**La huella del pegado a mano:** en `SUCESION` las filas 100-107 son un espejo perfecto
(100=107, 101=106, 102=105, 103=104): una tanda de 4 movimientos pegada dos veces, la segunda
en orden invertido. En `QUIQUE`, las filas 105-107 reaparecen en 114-116.

Detalle completo en `duplicadas_para_revisar.csv` (raíz del proyecto, ignorado por git).
Los scripts de exploración fueron temporales y no quedaron en el repo.

**Corrección de conteos** (la sesión 1 los tenía mal):

| Hoja | Con contenido | Vacías | Sesión 1 decía |
|---|---|---|---|
| SUCESION | 1309 | 1 | 1310 |
| QUIQUE | 1315 | 517 | 1832 |
| MARIELA | 219 | 0 | 219 |
| **Total** | **2843** | **518** | 3364 (incluía vacías y 3 encabezados) |

### F2.1 — El parser, con TDD

`web/src/lib/extracto.ts` + `extracto.test.ts`. Lógica pura: sin base, sin archivos, sin red.
`parsearImporte`, `fechaDeCelda`, `extraerCuit`, `extraerCoelsa`, `extraerTipo`, `huella`.

Dos ciclos rojo-verde, con el rojo mirado en los dos: primero `parsearImporte` (10 fallas de
aserción), después el resto (10 más). **36 tests en verde**, `tsc --noEmit` limpio, `eslint`
sin quejas.

| Decisión | Motivo |
|---|---|
| El importe vuelve como **string**, nunca `number` | `0.1 + 0.2 !== 0.3`. Lo recibe `NUMERIC(14,2)` |
| Dos separadores del mismo tipo = miles, sin ambigüedad | Un número tiene un solo punto decimal. `1.234.567` es 1234567 |
| Un separador con 1-2 dígitos detrás = decimal; con 3 = ambiguo | Es el único caso irresoluble |
| La fecha se lee **siempre en UTC** | Un día corrido rompería la tolerancia de ±1 día de F4 |
| `TIPOS` se ordena por largo con `.sort()`, no a mano | Si no, `TRANSF` le gana a `ING TRANSF` |

### Tres números del PLAN que estaban mal — verificados contra el archivo

El plan pedía verificar las suposiciones sobre los datos. Se hizo, y tres no aguantaron:

| Decía | Es | Por qué |
|---|---|---|
| 29 importes ambiguos | **1** | Las 29 filas con un solo separador tienen **todas 2 dígitos detrás** (`$ 16,00`): son decimales, no ambigüedades. La única fila irresoluble dice `############` |
| 95 COELSA | **84** | Hay 1268 filas con `TRANSF:`/`CREDIN:`, pero solo 84 traen un token de 22 caracteres. Los otros son textos cortos. Todos los COELSA miden exactamente 22 |
| Fechas como seriales de Excel | **`Date`** | `exceljs` devuelve las 2843 como `Date` a medianoche UTC. `fechaDeSerial` no servía y se reemplazó por `fechaDeCelda`, que toma las dos formas |

**La columna `IMPORTE` está guardada como texto en las 2843 filas.** Por eso el
`############` de una celda **es** el dato: el importe no existe en el archivo, no es un
problema de ancho de columna al mostrarlo. Queda `requiere_revision`.

Otros conteos medidos: CUIT en 90-93% según la hoja · 300 egresos · 96 filas (3,4%) sin tipo
reconocido, que **quedan en NULL a propósito** porque F4 nunca cruza por `tipo` · el archivo
trae mojibake (`COMPENSACIàN`), que **no se corrige**: sería adivinar.

**La validación de punta a punta contra el archivo real da 2822 huellas distintas** — clavado
con lo esperado. El dedup funciona.

`PLAN.md` quedó corregido en los tres números y en el criterio de listo de F2.

### F2.2 — El importador

`web/src/lib/importar.ts` + el script `pnpm importar`. Lee el `.xlsx` con `exceljs` (API
confirmada por context7), una `extracto_carga` por hoja, movimientos con `ON CONFLICT DO
NOTHING` sobre la `huella`, todo en una transacción.

**Los cinco criterios de listo, cumplidos:**

```
$ pnpm importar ../TRANSFERENCIAS.xlsx
cuenta    leidas  nuevas  duplicadas  aRevisar  sinFecha  fechaMin     fechaMax
SUCESION    1309    1298          11         1         0  2026-02-27   2026-08-05
QUIQUE      1315    1307           8         0         0  2026-03-02   2026-08-05
MARIELA      219     217           2         0         0  2026-02-23   2026-08-05
leídas 2843 · nuevas 2822 · duplicadas 21 · a revisar 1 · sin fecha 0

$ pnpm importar ../TRANSFERENCIAS.xlsx     # segunda corrida
leídas 2843 · nuevas 0 · duplicadas 2843   ← reimportar no inserta nada

En la base: 2822 movimientos · 84 COELSA · CUIT 90-93% según cuenta
            1 requiere_revision (y es la única con importe NULL) · 296 egresos
            fecha_min/fecha_max registrados por cuenta
```

| Decisión | Motivo |
|---|---|
| Una `extracto_carga` por hoja | La tabla tiene `cuenta_id`: una carga pertenece a una cuenta |
| `UNNEST` en vez de 2843 `INSERT` | Un parámetro por columna, no por celda: el límite de 65535 nunca aparece |
| La carga se inserta antes y se actualiza al final | Los movimientos la referencian, pero los conteos se saben después |
| Reimportar se permite, no se rechaza | El criterio pide que inserte 0, no que falle. Queda registrado el intento |
| Una fila sin fecha se cuenta y se saltea | `fecha` es NOT NULL. En este archivo son 0, pero no se descarta en silencio |
| Sin tests nuevos para el importador | La lógica está testeada en 2.1; esto es IO. Se verifica con la corrida real |

**El `ON CONFLICT DO NOTHING` deduplica dentro del mismo `INSERT`.** Las 21 filas repetidas
están en la misma sentencia y se descartaron igual: 2822 y no 2843. Queda demostrado por la
corrida, no por suposición.

**Pendiente menor:** `@types/node` está en `^20` y el runtime es Node 24.12, así que
`import.meta.main` no está tipado. Se resolvió con un cast local en `importar.ts`; el arreglo
de fondo es subir los tipos.

### F3.1 — Fixtures del motor

`web/src/lib/fixtures.ts` + `fixtures.test.ts`. **51 tests en verde**, `tsc` limpio, lint sin
quejas. 3 cuentas, 10 movimientos, 14 comprobantes, cada uno con su `caso` escrito en
castellano y su `estadoEsperado`. Todo inventado: por eso puede ir al repo.

**Las fixtures se validan a sí mismas.** Son la vara con la que se mide F4: si la vara está
torcida, los tests del motor pasan igual y no significan nada. Las 16 guardas verifican ids
únicos, que todo movimiento esperado exista, que los 6 estados y las 3 reglas estén cubiertos,
que un verificado traiga regla y confianza, que un ambiguo no se resuelva solo, que ningún
comprobante reclame un egreso, y que todo ingreso quede clasificado.

**Se comprobó que las guardas muerden**, rompiendo las fixtures a propósito:

| Mutación | La atrapó |
|---|---|
| Declarar un egreso como "sin comprobante" | `los movimientos sin comprobante son ingresos…` |
| Que el ambiguo se resuelva solo | `un ambiguo… ningún movimiento resuelto` |
| Apuntar a un movimiento inexistente | `cada movimiento esperado existe` + 2 más |
| Borrar el único caso ambiguo | `los seis estados están representados` |

Sin esto, 51 tests en verde a la primera no probaban nada.

**Casos que el PLAN no pedía y se agregaron:**

| Caso | Qué protege |
|---|---|
| Comprobante con 1 centavo de diferencia | El importe se compara exacto, no aproximado |
| Comprobante que coincide con un EGRESO | Los egresos se excluyen de la conciliación |
| Comprobante que coincide con un movimiento de OTRA cuenta | La cuenta destino tiene que coincidir |
| Cuenta nuestra pero sin extracto subido | Distinto de "la cuenta no es nuestra": los dos dan `no_verificable`, por motivos distintos |

**El caso del fin de semana es el que define la tolerancia.** Comprobante del viernes
2026-06-05 a las 21:46, movimiento el lunes 2026-06-08 (fechas verificadas contra el
calendario). Con ±1 día **corrido** este caso falla; solo pasa con ±1 día **hábil**. Es la
confirmación que sigue pendiente desde la sesión 1, y ahora está escrita como test.

**Decisión nueva, anotada acá porque F4 la va a necesitar:** los movimientos 5 y 6 son
candidatos del comprobante ambiguo y **no** se listan como "sin comprobante". Decir las dos
cosas del mismo movimiento sería contradictorio. Se revisa al cerrar F4.

### F3.2 — Test de integración del importador, y la base de tests aparte

`web/src/lib/importar.test.ts` genera un `.xlsx` de 13 filas en el temporal, lo importa, lo
verifica y lo borra. **No se commitea un binario:** un `.xlsx` en el repo se desincroniza del
test que lo usa.

El archivo tiene lo mismo que el real, en chico: formatos AR y US en la misma columna, un
egreso, el signo puesto **después** del `$`, una celda `############`, un `$ 1.500` ambiguo,
una fila repetida, una fila con solo `SALDO`, y COELSA tras `TRANSF:` y tras `CREDIN:`.

**Por qué existe:** F2 se había verificado a mano una sola vez. Sin este test, tocar
`parsearImporte` dejaba el importador roto con `pnpm test` en verde.

**La base de tests aparte.** `conciliador_test`, creada por `pnpm db:test:reiniciar`. El
`DATABASE_URL` va escrito en el script `test` de `package.json`, no en un `.env`: se ve de un
vistazo que los tests no apuntan a la base real. Confirmado tras correr todo: la base real
sigue con sus 2822 movimientos.

**Se comprobó que los tests muerden**, rompiendo el código a propósito:

| Mutación | La atrapó |
|---|---|
| El decimal siempre es el punto (`368.500,00` → `368,50`) | `el formato argentino no se lee como centavos` +2 |
| Adivinar el importe ambiguo en vez de marcarlo | `un importe irresoluble queda en NULL…` +2 |
| Perder el signo de los egresos | `un egreso entra en negativo y marcado como egreso` +2 |
| Dejar de saltear las filas vacías | `la hoja con la fila repetida y la vacía cuenta bien` |

La primera es exactamente el bug que el `PLAN.md` marca como el que puede hundir el proyecto:
un importe mal parseado que no rompe nada visible y produce una acusación falsa. Ahora hay un
test que lo agarra.

### F4 — El motor

`web/src/lib/motor.ts` + `motor.test.ts`. Lógica pura: sin base, sin red, sin archivos.
**32 tests**, los 14 casos de las fixtures más 18 bordes armados a mano.

**Trabaja sobre el lote entero, no de a un comprobante.** Dos de los seis estados solo existen
mirando el conjunto: `duplicado` necesita ver que otro comprobante reclama el mismo
movimiento, y `sin comprobante` que ninguno reclamó ese ingreso.

| Decisión | Motivo |
|---|---|
| **Sin calendario de feriados** | Se desactualiza solo. El error que produce su ausencia es el seguro: un feriado hace que 1 día hábil parezca 2 y el comprobante cae en `sospechoso` —que pide revisión— en vez de `verificado` |
| Se cae del escalón 2 al 3 cuando el movimiento **no tiene** CUIT | El extracto solo deja parsear CUIT en el 90-93% de las filas. Exigirlo en los dos lados dejaría el resto sin conciliar nunca. Baja a confianza media |
| Un CUIT que **se contradice** nunca matchea | Verificar el pago de una persona con el movimiento de otra es el peor error posible |
| Importes comparados como **enteros de centavos** (`BigInt`) | Nunca `number`. Es plata |
| Si el dinero pudo caer **fuera** del extracto → `no_verificable` | Un comprobante del último día cubierto podría impactar el día hábil siguiente, que el extracto ya no muestra. No se puede probar que faltó |
| El COELSA gana aunque el importe difiera | El COELSA identifica la transferencia; un importe distinto es un error de extracción, no otra transferencia |

**Las 6 mutaciones fueron atrapadas**, incluida la que más importa:

| Mutación | Tests caídos |
|---|---|
| **Colapsar `no_verificable` en `sospechoso`** | 3 — el error que el README dice que destruye la confianza |
| Días corridos en vez de hábiles | 4 |
| Tolerar un centavo | 4 |
| Aceptar CUIT contradictorio | 2 |
| No marcar duplicados | 3 |
| Dejar entrar los egresos | 3 |

### Migración 002 — lo que F1 dejó abierto

F4 obligó a cerrar las dos preguntas que venían de F1:

- **`UNIQUE (comprobante_id)`** — un comprobante tiene UN veredicto vigente, no un historial.
  Sin esto cada corrida del motor apila una fila más. El historial que importa es el de las
  decisiones humanas, y lo guardan `decidido_por` y `decidido_en`.
- **`movimiento_pretendido`** — el movimiento que un duplicado reclama sin quedárselo.
  `movimiento_id` no servía: su índice único —el que hace imposible el doble cobro— impide
  justamente que dos comprobantes lo apunten.
- **`candidatos INTEGER[]`** — los del ambiguo, para la pantalla que los resuelve. Array
  nativo y no tabla puente: se leen y escriben siempre juntos.

### El puente motor ↔ base

`web/src/lib/conciliacion.ts`. Carga, corre la cascada, guarda. **No vuelve a decidir lo que
decidió una persona:** los veredictos con `decidido_por = 'persona'` quedan intactos. Si el
motor pudiera pisarlos, resolver un ambiguo a mano no serviría de nada.

Un test encontró un bug real acá: `sinComprobante` no miraba `movimiento_pretendido`, así que
el movimiento disputado por dos duplicados aparecía además como "sin comprobante".

**Dos arreglos de infraestructura de tests:**

- Los archivos de test corrían **en paralelo** contra la misma base y se pisaban: los
  resultados oscilaban entre 111/0 y 82/29. Se agregó `--test-concurrency=1`. Verificado
  estable en 3 corridas seguidas.
- `TRUNCATE ... RESTART IDENTITY` dejaba las secuencias en 1 mientras las fixtures insertan
  ids explícitos, y el siguiente `INSERT` con serial chocaba. Se adelantan con `setval`.

### Los tres documentos, alineados

`README.md` corregido a pedido del usuario (`CLAUDE.md` lo prohíbe sin pedido explícito).
Lo que decía y lo que se midió:

| Decía | Es |
|---|---|
| 3364 movimientos | 2843 filas con contenido → **2822 movimientos** |
| 95 COELSA | **84**, todos de 22 caracteres |
| CUIT en 64-93% | **90-93%** |
| 20 filas repetidas | **21 pares**, saldo incluido |
| 29 importes ambiguos | **1**, y es una celda `############` |
| Fechas como seriales de Excel | Objetos `Date` a medianoche UTC |
| `viejo./comprobantesReales/` | La carpeta se renombró a `viejo/` en F0 |

Se le agregaron dos secciones que no tenía: **Cómo se corre** (los comandos reales, con el
aviso de los CBU faltantes) y **Estado del proyecto**. `PLAN.md` quedó con un encabezado que
aclara que dice *qué hacer*, no *qué está hecho*, y que ante contradicción gana la bitácora.

### F5 — La interfaz

Cuatro pantallas, sin login, sin gráficos, sin animaciones.

| Ruta | Qué hace |
|---|---|
| `/` | Tablero: los 6 estados con su conteo y su explicación, filtro por estado y cuenta, botón Recalcular |
| `/extracto` | Subir el Excel y ver el resumen por cuenta |
| `/comprobante` | Imagen + los 16 campos agrupados, guardar y conciliar |
| `/resolver` | Los ambiguos con sus candidatos al lado y un botón por candidato |

**Next 16 confirmado leyendo `node_modules/next/dist/docs/`,** como manda la regla. Lo que
cambió respecto de lo que el modelo tiene aprendido: **`params` y `searchParams` son
Promises** y hay que esperarlas; `cacheComponents` está apagado, así que rige el modelo de
caché anterior y las páginas que leen Postgres llevan `export const dynamic = 'force-dynamic'`.

| Decisión | Motivo |
|---|---|
| El Excel subido nunca toca el disco | `importarExtracto` acepta `Buffer` además de ruta |
| Las imágenes van a `web/comprobantes/` | Ignorado por git. Los datos reales no salen de la máquina |
| La misma imagen se rechaza al subirla dos veces | `hash_imagen UNIQUE`, chequeado antes de escribir |
| Monto y fecha son los únicos campos obligatorios | Sin eso no hay nada que cruzar. El resto queda `null`: no se completa por defecto |
| Cada estado muestra **qué significa y qué hacer** | "No verificable" y "sospechoso" se parecen si uno solo mira una etiqueta, y confundirlos es acusar a alguien que pagó bien |

**No se usó la skill `ui-ux-pro-max`** que la tabla de `CLAUDE.md` sugiere para pantallas: la
fase pide explícitamente sin dashboard, sin gráficos y sin animaciones, que es justo lo que esa
skill optimiza. Queda a mano si querés una pasada de diseño.

**Verificado levantando el servidor:** las cuatro rutas responden 200 y el tablero muestra los
2526 ingresos sin comprobante (2822 menos 296 egresos).

