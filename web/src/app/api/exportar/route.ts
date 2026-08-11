import ExcelJS from 'exceljs'
import { db } from '@/lib/db'

/**
 * Exporta a Excel el cruce comprobantes ↔ extracto, con las celdas pintadas.
 *
 *   GET /api/exportar?que=comprobantes|extracto|ambas&periodo=todo|hoy|7d|mes|rango
 *                    &desde=YYYY-MM-DD&hasta=YYYY-MM-DD
 *
 * Los colores dicen CON QUÉ REGLA se encontró, no si el pago es legítimo:
 *
 *   verde    nro de transacción + CUIT coinciden       → 90%
 *   amarillo solo monto y fecha, puede ser casualidad  → 50%
 *   rojo     no se encontró
 *
 * Rojo NO significa "es falso": significa "no lo encontré", que es la regla 4
 * del proyecto. Cada hoja lo dice con palabras arriba de todo, porque un color
 * suelto en una planilla se interpreta solo y se interpreta mal.
 *
 * Usa la misma cascada que /encontrar y no `motor.ts`, que cruza por
 * `cuenta.cbu` y hoy daría "no verificable" en todo.
 */

const VERDE = 'FFD1FADF'
const AMARILLO = 'FFFEF0C7'
const ROJO = 'FFFEE4E2'
const GRIS = 'FFEAECF0'

const pintar = (celda: ExcelJS.Cell, argb: string) => {
  celda.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb } }
}

/** El rango de fechas elegido, o null si es "todo". */
function rango(url: URL): { desde: string, hasta: string } | null {
  const hoy = new Date().toISOString().slice(0, 10)
  const menos = (dias: number) =>
    new Date(Date.now() - dias * 86_400_000).toISOString().slice(0, 10)

  switch (url.searchParams.get('periodo')) {
    case 'hoy': return { desde: hoy, hasta: hoy }
    case '7d': return { desde: menos(7), hasta: hoy }
    case 'mes': return { desde: hoy.slice(0, 8) + '01', hasta: hoy }
    case 'rango': {
      const desde = url.searchParams.get('desde')
      const hasta = url.searchParams.get('hasta')
      // Un rango a medio llenar se trata como "todo" en vez de fallar: es un
      // formulario, no una API, y el usuario ya apretó Descargar.
      return desde && hasta ? { desde, hasta } : null
    }
    default: return null
  }
}

function leyenda(hoja: ExcelJS.Worksheet, texto: string) {
  hoja.addRow([texto])
  hoja.mergeCells(1, 1, 1, 8)
  hoja.getRow(1).font = { size: 11, italic: true }
  hoja.getRow(1).height = 30
  hoja.getRow(1).alignment = { wrapText: true, vertical: 'middle' }
  hoja.addRow([])
}

/** Una fila por comprobante: se encontró en el extracto o no. */
async function hojaComprobantes(wb: ExcelJS.Workbook, r: ReturnType<typeof rango>) {
  const { rows } = await db.query(
    `WITH c AS (
       SELECT id, archivo, monto, fecha, cuit_emisor, referencia,
              revisado_en IS NOT NULL AS revisado
       FROM comprobante
       WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico'
         AND ($1::date IS NULL OR fecha BETWEEN $1::date AND $2::date)
     ),
     r1 AS (
       SELECT c.id AS comp, m.id AS mov, '90'::text AS regla
       FROM c JOIN movimiento m
         ON m.nro_transaccion = c.referencia AND m.cuit_emisor = c.cuit_emisor
       WHERE c.referencia IS NOT NULL AND c.cuit_emisor IS NOT NULL
     ),
     r2 AS (
       SELECT c.id AS comp, m.id AS mov, '50'::text AS regla
       FROM c JOIN movimiento m
         ON m.importe = c.monto AND m.fecha = c.fecha AND m.es_ingreso
       WHERE c.monto IS NOT NULL AND c.fecha IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM r1 WHERE r1.comp = c.id)
     ),
     todos AS (SELECT * FROM r1 UNION ALL SELECT * FROM r2),
     resumen AS (
       SELECT comp, min(regla) AS regla, count(*) AS candidatos,
              CASE WHEN count(*) = 1 THEN min(mov) END AS mov
       FROM todos GROUP BY comp
     )
     SELECT c.archivo, c.monto, to_char(c.fecha,'YYYY-MM-DD') AS fecha,
            c.cuit_emisor AS cuit, c.referencia, c.revisado,
            s.regla, coalesce(s.candidatos, 0)::int AS candidatos,
            m.hoja, m.fila, m.nro_transaccion AS "movNro"
     FROM c
     LEFT JOIN resumen s ON s.comp = c.id
     LEFT JOIN movimiento m ON m.id = s.mov
     ORDER BY (s.regla IS NULL) DESC, s.regla, c.archivo`,
    [r?.desde ?? null, r?.hasta ?? null])

  const h = wb.addWorksheet('Comprobantes')
  leyenda(h, 'VERDE = encontrado por nro de transacción + CUIT (90% de confianza).  ' +
    'AMARILLO = coincide solo en monto y fecha, puede ser casualidad (50%).  ' +
    'ROJO = no se encontró en el extracto. Rojo NO quiere decir que el pago sea falso: ' +
    'quiere decir que con los datos que hay no se pudo ubicar.')

  h.addRow(['archivo', 'monto', 'fecha', 'CUIT emisor', 'referencia',
    'resultado', 'hoja del Excel', 'fila del Excel', 'revisado'])
  const cabecera = h.lastRow!
  cabecera.font = { bold: true }
  cabecera.eachCell((c) => pintar(c, GRIS))

  for (const f of rows) {
    const estado = f.candidatos > 1 ? `ambiguo · ${f.candidatos} candidatos`
      : f.regla === '90' ? 'encontrado · 90%'
        : f.regla === '50' ? 'coincide monto+fecha · 50%'
          : 'no encontrado'
    const fila = h.addRow([f.archivo, f.monto ? Number(f.monto) : null, f.fecha,
      f.cuit, f.referencia, estado, f.hoja, f.fila, f.revisado ? 'sí' : 'no'])
    const color = f.candidatos > 1 ? AMARILLO
      : f.regla === '90' ? VERDE : f.regla === '50' ? AMARILLO : ROJO
    fila.eachCell((c) => pintar(c, color))
    fila.getCell(2).numFmt = '#,##0.00'
  }
  h.columns.forEach((c, i) => { c.width = [26, 14, 12, 14, 16, 26, 15, 14, 10][i] ?? 14 })
}

/** Una fila por ingreso del extracto: algún comprobante lo reclama o ninguno. */
async function hojaExtracto(wb: ExcelJS.Workbook, r: ReturnType<typeof rango>) {
  const { rows } = await db.query(
    `WITH c AS (
       SELECT id, archivo, monto, fecha, cuit_emisor, referencia
       FROM comprobante
       WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico'
     ),
     r1 AS (
       SELECT m.id AS mov, c.archivo, '90'::text AS regla
       FROM c JOIN movimiento m
         ON m.nro_transaccion = c.referencia AND m.cuit_emisor = c.cuit_emisor
       WHERE c.referencia IS NOT NULL AND c.cuit_emisor IS NOT NULL
     ),
     r2 AS (
       SELECT m.id AS mov, c.archivo, '50'::text AS regla
       FROM c JOIN movimiento m
         ON m.importe = c.monto AND m.fecha = c.fecha AND m.es_ingreso
       WHERE c.monto IS NOT NULL AND c.fecha IS NOT NULL
     ),
     reclamos AS (
       SELECT mov, min(regla) AS regla, count(*)::int AS cuantos,
              string_agg(DISTINCT archivo, ', ') AS archivos
       FROM (SELECT * FROM r1 UNION ALL SELECT * FROM r2) t GROUP BY mov
     )
     SELECT m.hoja, m.fila, to_char(m.fecha,'YYYY-MM-DD') AS fecha,
            m.nro_transaccion AS nro, m.descripcion, m.importe,
            m.cuit_emisor AS cuit,
            k.regla, coalesce(k.cuantos, 0) AS cuantos, k.archivos
     FROM movimiento m
     LEFT JOIN reclamos k ON k.mov = m.id
     WHERE m.es_ingreso
       AND ($1::date IS NULL OR m.fecha BETWEEN $1::date AND $2::date)
     ORDER BY m.hoja, m.fila`,
    [r?.desde ?? null, r?.hasta ?? null])

  const h = wb.addWorksheet('Extracto')
  leyenda(h, 'Ingresos del extracto. VERDE = un comprobante lo reclama por nro de ' +
    'transacción + CUIT (90%). AMARILLO = coincide solo en monto y fecha (50%). ' +
    'ROJO = ningún comprobante cargado corresponde a este movimiento — lo más ' +
    'probable es que todavía no se haya subido, no que falte la plata. Los egresos ' +
    'no se listan: nunca tienen comprobante de transferencia recibida.')

  h.addRow(['hoja', 'fila', 'fecha', 'NRO TRANSACCION', 'DESCRIPCION', 'IMPORTE',
    'CUIT', 'comprobante'])
  const cabecera = h.lastRow!
  cabecera.font = { bold: true }
  cabecera.eachCell((c) => pintar(c, GRIS))

  for (const f of rows) {
    const quien = f.cuantos > 1 ? `${f.cuantos} comprobantes — ambiguo` : f.archivos ?? '—'
    const fila = h.addRow([f.hoja, f.fila, f.fecha, f.nro, f.descripcion,
      f.importe ? Number(f.importe) : null, f.cuit, quien])
    const color = f.cuantos > 1 ? AMARILLO
      : f.regla === '90' ? VERDE : f.regla === '50' ? AMARILLO : ROJO
    fila.eachCell((c) => pintar(c, color))
    fila.getCell(6).numFmt = '#,##0.00'
  }
  h.columns.forEach((c, i) => { c.width = [11, 7, 12, 18, 46, 14, 14, 26][i] ?? 14 })
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const que = url.searchParams.get('que') ?? 'comprobantes'
  const r = rango(url)

  const wb = new ExcelJS.Workbook()
  wb.created = new Date()
  if (que !== 'extracto') await hojaComprobantes(wb, r)
  if (que !== 'comprobantes') await hojaExtracto(wb, r)

  const buffer = await wb.xlsx.writeBuffer()
  const sufijo = r ? `_${r.desde}_a_${r.hasta}` : ''
  return new Response(buffer as ArrayBuffer, {
    headers: {
      'Content-Type':
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Disposition':
        `attachment; filename="conciliacion_${que}${sufijo}.xlsx"`,
    },
  })
}
