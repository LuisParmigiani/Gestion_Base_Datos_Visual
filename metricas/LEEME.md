# Los CSV del tablero de Looker Studio

Tres archivos. **Ninguno lleva un dato bancario real**: son aciertos del modelo, curvas de
entrenamiento y configuración de las corridas.

| Archivo | Qué tiene | Se regenera con |
|---|---|---|
| `extraccion.csv` | Una fila por **corrida × comprobante × campo**, con `acierto` 0/1 | `cd web && node --env-file=.env.local comparar-lora.ts` |
| `curvas_loss.csv` | La curva de loss de las 10 corridas, en un solo archivo | `ia/metricas.sh` |
| `corridas.csv` | Configuración y resultado de cada entrenamiento | A mano — son 6 filas |

## Por qué `extraccion.csv` está en formato largo

Porque con las cuatro dimensiones (`corrida`, `comprobante_id`, `entidad`, `campo`) el
tablero calcula **cualquier** corte él solo: por campo, por banco, sin `tipo_operacion`, solo
Mercado Pago. Exportar un CSV por cada vista obligaría a mantener los mismos cortes en dos
lugares, y el día que se cambie uno los números dejarían de coincidir.

En Looker Studio la métrica es siempre la misma: **`AVG(acierto)` formateado como
porcentaje**. Cambian las dimensiones, no la cuenta.

## Cómo se sube

**Google Sheets o "File Upload", nunca el conector de PostgreSQL.** Conectar la base
obligaría a exponerla a internet y abrir el firewall a `142.251.74.0/23`, lo que rompe la
regla de que los datos no salen de la máquina. Con un CSV se ve exactamente qué se sube antes
de subirlo.

## Las tres páginas del tablero

**1 · Calidad de extracción** (`extraccion.csv`)
- Barras: `AVG(acierto)` por `corrida` — la historia completa en un gráfico
- Barras horizontales: `AVG(acierto)` por `campo`, con `corrida` como serie
- Tabla: `entidad` × `corrida`
- Filtro: `campo` ≠ `tipo_operacion`, `moneda` ← **el corte honesto**

**2 · El entrenamiento** (`curvas_loss.csv` + `corridas.csv`)
- Líneas: `loss` por `paso`, una serie por `corrida`
- Tabla: las corridas con su `lr`, `alpha` y resultado

> El gráfico que más dice del proyecto: la curva de `lora_v1` **bajando** al lado de su
> `acierto_honesto` en **0,0**. Una métrica de entrenamiento no valida una capacidad que no
> mide.

**3 · Demo del tablero de conciliación** — pendiente, ver abajo.

## ⚠️ Por qué la página 3 todavía no se puede armar

Necesita datos de conciliación que hoy no existen en un estado usable:

- `motor.ts` devuelve `no_verificable` en los 69 comprobantes porque las tres cuentas tienen
  el CBU en NULL. Un tablero de los seis estados saldría con **una sola barra**.
- Los 20 comprobantes sintéticos cargados tienen **las etiquetas rotas** (vienen del
  generador viejo, que inventaba campos) y hay que recargarlos.

Se destraba con cualquiera de las dos: aprobar los CBU propios en `/cbu`, o recargar los
sintéticos desde el dataset nuevo. Hasta entonces, un tablero de conciliación mostraría un
sistema que no funciona, y el que no funciona es el motor viejo — no el proyecto.
