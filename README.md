# Conciliador de Comprobantes Bancarios

Sistema local para verificar que las transferencias que dicen haberse hecho, efectivamente
entraron al banco.

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

Al analizar `Macro.jpeg` (transferencia real de $250.000) no aparece en ninguno de los 2822
movimientos del extracto. No es falsa: fue a una cuenta de Mercado Pago que no está entre las tres
cuentas cargadas.

**"No aparece en el extracto" no significa "es falso".** Significa "no aparece en el extracto".
Si el sistema colapsa esos dos estados en uno, acusa de tramposos a clientes que pagaron bien,
y una sola acusación falsa destruye la confianza en toda la herramienta.

Regla: **el sistema solo dice "sospechoso" cuando puede probar que tenía cómo verlo y no lo vio.**

---

## Los datos reales

### Extracto del banco (`TRANSFERENCIAS.xlsx`)

Tres hojas = **tres cuentas bancarias distintas**: `SUCESION`, `QUIQUE`, `MARIELA`.
**2843 filas con contenido** entre 2026-02-23 y 2026-08-05, que dejan **2822 movimientos**
una vez descartadas las repetidas.

| Hoja | Filas con contenido | Filas vacías |
|---|---|---|
| SUCESION | 1309 | 1 |
| QUIQUE | 1315 | 517 |
| MARIELA | 219 | 0 |
| **Total** | **2843** | **518** |

Columnas: `FECHA | NRO TRANSACCION | DESCRIPCION | IMPORTE | SALDO`
(la columna `F` son anotaciones personales ajenas al proyecto — **se ignora**)

Lo que el análisis del archivo reveló, y que el importador tiene que manejar sí o sí:

| Hallazgo | Detalle | Consecuencia |
|---|---|---|
| **Dos formatos de número mezclados** | 2481 filas `$ 368.500,00` (AR) vs 332 filas `$ 16,000.00` (US), en la misma columna y guardadas como texto | Un parser ingenuo lee 368.500,00 como 368,50 y descuadra todo en silencio |
| **Un solo importe es irresoluble** | Una celda dice literalmente `############`. Como la columna es texto, ese `###` **es** el dato | Queda sin importe y marcada para revisar. No se adivina |
| **El SALDO no se usa** | Es el saldo de la cuenta al momento — información del banco, no del proyecto | Se lee y se descarta. No se modela, no se muestra |
| **El ID COELSA está, pero poco** | 84 de 2843 filas (3,0%), siempre de 22 caracteres: `TRANSF:R7ZG0QNDW4YMXVWD9EXYPO-…` | Camino exacto cuando está; el 97% se cruza por otro lado |
| **El CUIT sí está casi siempre** | Embebido en la descripción, parseable en 90-93% según la hoja | **Es la clave de cruce principal** |
| **Los nombres vienen truncados** | `ALONSO, H`, `PODESTA/M`, `ORSI/JAVI` (8-16 caracteres) | Inservibles para matchear solos |
| **`NRO TRANSACCION` no es único** | 1309 presentes / 1286 distintos | No sirve como clave primaria |
| **Hay filas repetidas** | 21 pares 100% idénticos, saldo incluido | El Excel es un pegado manual de descargas superpuestas. Se descartan solas |
| **Los egresos vienen en negativo** | 296 filas (Movistar, AFIP, IIBB, tasas) | Solo se concilian los ingresos: quedan 2526 |
| **Las fechas son objetos `Date`** | Todas a medianoche UTC, no seriales de Excel | Se leen en UTC: un día corrido rompería la tolerancia de ±1 día hábil |

### Comprobantes

52 imágenes reales en `viejo/comprobantesReales/` (mayoría capturas de WhatsApp).
Provienen de otra fuente y de otro período, así que **no cruzan con este extracto**: sirven
para medir la extracción de la IA, no para probar la conciliación.

16 campos por comprobante:

```
tipo_operacion  monto  moneda  fecha  hora
nombre_emisor   cuit_emisor    cbu_cvu_emisor    banco_emisor
nombre_receptor cuit_receptor  cbu_cvu_receptor  banco_receptor
concepto  referencia  coelsa_id
```

---

## Cómo se cruzan las dos fuentes

Cascada: se corta en la primera regla que da resultado.

```
1. ID COELSA idéntico
   └─► verificado, confianza alta          (~3% de los casos, certeza total)

2. CUIT emisor + importe exacto + fecha ±1 día hábil
   └─► verificado, confianza alta          (el camino principal)

3. Importe exacto + fecha ±1 día hábil, sin CUIT
   ├─ un solo candidato  ─► verificado, confianza media
   └─ varios candidatos  ─► ambiguo, decide una persona

4. Sin candidatos
   ├─ ¿la cuenta destino está cargada y el extracto cubre la fecha?
   │   ├─ sí ─► sospechoso
   │   └─ no ─► no verificable
```

**Un movimiento del banco solo puede ser reclamado por un comprobante.** Si dos comprobantes
apuntan al mismo movimiento, ambos quedan marcados como duplicado. Es la defensa contra el
reenvío del mismo comprobante para dos pagos distintos.

---

## Stack

| Capa | Elección | Por qué |
|---|---|---|
| Base de datos | **PostgreSQL** (local) | Robusto, y ya es la preferencia. SQLite descartado a propósito |
| Web | **TypeScript, Next.js** | Un solo proceso sirve interfaz + API + subida de archivos |
| Acceso a datos | `pg` + SQL plano | Sin ORM hasta que duela. 6 tablas no justifican una capa más |
| Lectura de Excel | `exceljs` en TS | El import es del lado web; no hace falta pasar por Python |
| Extracción IA | **Python + MLX + Qwen2-VL-7B 4-bit** | Corre en Apple Silicon, sin costo por token, sin mandar datos afuera |
| Puente web↔IA | **FastAPI local** | Mantiene el modelo cargado en memoria entre comprobantes |
| Entrenamiento | **LoRA** vía `mlx-vlm` | Requisito de la materia. Adapta ~1% de los pesos |

**Corre 100% local en MacBook Pro M4 Pro (24 GB).** No se despliega. MLX solo funciona en
Apple Silicon: no hay servidor Linux que valga, y además los datos bancarios reales no salen
de la máquina.

---

## Alcance

### Entra en la versión 1

- Importar extractos de Excel a Postgres, sin duplicar, de varias cuentas
- Cargar comprobantes (imagen o PDF) y extraer los 16 campos
- Conciliar y clasificar en los seis estados
- Pantalla para revisar, filtrar y resolver los casos ambiguos a mano
- Historial: qué se verificó, cuándo, y quién decidió los casos dudosos

### Queda para después, en este orden

1. **Conexión con la API de deudas.** Hoy el sistema no manda información a ningún lado:
   solo compara y opina. La deuda vive en otro sistema y se integra al final.
2. **Alta automática de comprobantes** desde la API en vez de subida manual.

### Fuera de alcance, decidido

- **Análisis forense de imagen** (detectar Photoshop, metadatos). El extracto ya dice la
  verdad; el forense agrega complejidad y falsos positivos sin agregar certeza.
- **Multiusuario y permisos.** Uso local, una persona.
- **Deploy en la nube.** Ver la restricción de MLX.

---

## Cómo se corre

Requiere PostgreSQL 18 levantado (Postgres.app **no** arranca solo) y `pnpm`. Nunca `npm`.

```bash
cd web
pnpm db:migrar                          # crea las tablas y siembra las 3 cuentas
pnpm importar ../TRANSFERENCIAS.xlsx    # Excel → Postgres, sin duplicar
pnpm dev                                # localhost:3000
pnpm test                               # la suite completa
```

Cuatro pantallas: **Tablero** (los seis estados, con filtro por estado y cuenta),
**Subir extracto**, **Cargar comprobante** (los 16 campos a mano) y **Resolver** (los
ambiguos, con sus candidatos al lado).

> **Falta un dato para que muestre un `verificado`:** los CBU de las tres cuentas están en
> `NULL`. El motor cruza el CBU receptor del comprobante contra el de la cuenta, así que sin
> eso todo da `no verificable` — que es lo correcto, pero deja el tablero mudo.

## Estado del proyecto

**El Bloque A está terminado:** el sistema importa, concilia y se usa a mano, sin una línea
de IA. El Bloque B —el fine-tuning— no empezó.

El plan fase por fase está en **[`.claude/PLAN.md`](.claude/PLAN.md)**, el estado del día en
**[`.claude/BITACORA.md`](.claude/BITACORA.md)**, y las reglas de trabajo en
**[`.claude/CLAUDE.md`](.claude/CLAUDE.md)**.

## La carpeta `viejo/`

Intento anterior, no funcional. **No se borra, no se modifica, no se importa.** Se consulta.

Lo que sirve de ahí:

- `generar_sinteticos.py` — 10 plantillas de comprobantes con verdad de referencia automática
- `train.jsonl` — 300 ejemplos sintéticos con los 16 campos
- `comprobantesReales/` — las 52 imágenes reales
- El bug documentado: el formato `image/prompt/answer` **no es** el que espera `mlx_vlm.lora`
  0.1.15 (`messages`/`images`). Por eso el entrenamiento nunca corrió. Hay que arreglarlo.
