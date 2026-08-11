import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import ExcelJS from 'exceljs'
import { db } from './db.ts'
import {
  parsearImporte, fechaDeCelda, extraerCuit, extraerCoelsa, extraerTipo, huella,
} from './extracto.ts'

export type ResumenCuenta = {
  cuenta: string
  leidas: number
  nuevas: number
  duplicadas: number
  aRevisar: number
  sinFecha: number
  fechaMin: string | null
  fechaMax: string | null
}

const texto = (v: unknown): string => {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object' && v !== null && 'result' in v) return String(v.result).trim()
  if (typeof v === 'object' && v !== null && 'text' in v) return String(v.text).trim()
  return String(v).trim()
}

/**
 * Excel → Postgres. Una `extracto_carga` por hoja, porque una carga pertenece
 * a una cuenta. El mismo archivo se puede subir dos veces: la `huella` UNIQUE
 * hace que la segunda vez entren 0 filas.
 */
export async function importarExtracto(
  origen: string | Buffer, nombre?: string,
): Promise<ResumenCuenta[]> {
  // Desde la web llega un Buffer y no una ruta: el archivo subido nunca toca
  // el disco. Desde `pnpm importar`, una ruta.
  const bytes = typeof origen === 'string' ? await readFile(origen) : origen
  const hashArchivo = createHash('sha256').update(bytes).digest('hex')
  const archivo = nombre ?? (typeof origen === 'string' ? origen.split('/').pop()! : 'subido.xlsx')

  const wb = new ExcelJS.Workbook()
  // El cast es por los tipos, no por el runtime: `exceljs` declara el Buffer de
  // una versión de @types/node distinta de la instalada. El valor es correcto.
  await wb.xlsx.load(bytes as unknown as Parameters<typeof wb.xlsx.load>[0])

  const { rows: cuentas } = await db.query<{ id: number; nombre: string }>(
    'SELECT id, nombre FROM cuenta')
  const porNombre = new Map(cuentas.map((c) => [c.nombre, c.id]))

  const cliente = await db.connect()
  try {
    await cliente.query('BEGIN')
    const resumen: ResumenCuenta[] = []

    for (const hoja of wb.worksheets) {
      const cuentaId = porNombre.get(hoja.name)
      if (cuentaId === undefined) {
        throw new Error(
          `La hoja "${hoja.name}" no coincide con ninguna cuenta cargada ` +
          `(${[...porNombre.keys()].join(', ')}). No se importa nada.`)
      }

      // Columnas: FECHA · NRO TRANSACCION · DESCRIPCION · IMPORTE · SALDO.
      // SALDO no se lee: es información del banco, no del proyecto.
      const fechas: string[] = [], nros: (string | null)[] = [], descs: string[] = []
      const crudos: string[] = [], importes: (string | null)[] = []
      const ingresos: boolean[] = [], revisar: boolean[] = []
      const cuits: (string | null)[] = [], coelsas: (string | null)[] = []
      const tipos: (string | null)[] = [], huellas: string[] = []
      let leidas = 0, sinFecha = 0
      // De qué fila del Excel salió cada huella, para que /encontrar pueda
      // decirle a una persona dónde mirar. Se queda con la PRIMERA aparición,
      // igual que el `ON CONFLICT DO NOTHING` de abajo: si el Excel repite una
      // fila, la que existe en la base es la primera.
      const filaDe = new Map<string, number>()

      hoja.eachRow((row, nro) => {
        if (nro === 1) return // encabezado
        const celdaFecha = row.getCell(1).value
        const nroTx = texto(row.getCell(2).value)
        const desc = texto(row.getCell(3).value)
        const crudo = texto(row.getCell(4).value)
        if (!celdaFecha && !nroTx && !desc && !crudo) return // fila vacía: se saltea

        leidas++
        const fecha = fechaDeCelda(celdaFecha)
        if (fecha === null) { sinFecha++; return } // sin fecha no hay movimiento

        const imp = parsearImporte(crudo)
        fechas.push(fecha)
        nros.push(nroTx || null)
        descs.push(desc)
        crudos.push(crudo)
        importes.push(imp.importe)
        ingresos.push(imp.esIngreso)
        revisar.push(imp.ambiguo)
        cuits.push(extraerCuit(desc))
        coelsas.push(extraerCoelsa(desc))
        tipos.push(extraerTipo(desc))
        const hu = huella({
          cuenta: hoja.name, fecha, nro: nroTx, importeCrudo: crudo, descripcion: desc,
        })
        huellas.push(hu)
        if (!filaDe.has(hu)) filaDe.set(hu, nro)
      })

      const fechaMin = fechas.length ? fechas.reduce((a, b) => (a < b ? a : b)) : null
      const fechaMax = fechas.length ? fechas.reduce((a, b) => (a > b ? a : b)) : null

      // La carga se inserta antes que los movimientos porque estos la referencian.
      // Los conteos reales se saben recién después, así que se actualizan al final.
      const { rows: [carga] } = await cliente.query<{ id: number }>(
        `INSERT INTO extracto_carga
           (cuenta_id, archivo, hash_archivo, filas_leidas, filas_nuevas,
            filas_duplicadas, fecha_min, fecha_max)
         VALUES ($1, $2, $3, $4, 0, 0, $5, $6) RETURNING id`,
        [cuentaId, archivo, hashArchivo, leidas, fechaMin, fechaMax])

      // UNNEST y no 2843 INSERT sueltos: un parámetro por columna en vez de
      // uno por celda, así el límite de 65535 parámetros nunca aparece.
      const res = await cliente.query(
        `INSERT INTO movimiento
           (cuenta_id, carga_id, fecha, nro_transaccion, descripcion, importe_crudo,
            importe, es_ingreso, requiere_revision, cuit_emisor, coelsa_id, tipo, huella)
         SELECT $1, $2, f, n, d, ic, i, ei, rr, cu, co, ti, hu
         FROM UNNEST($3::date[], $4::text[], $5::text[], $6::text[], $7::numeric[],
                     $8::boolean[], $9::boolean[], $10::text[], $11::text[],
                     $12::text[], $13::text[])
              AS x(f, n, d, ic, i, ei, rr, cu, co, ti, hu)
         ON CONFLICT (huella) DO NOTHING`,
        [cuentaId, carga.id, fechas, nros, descs, crudos, importes,
         ingresos, revisar, cuits, coelsas, tipos, huellas])

      const nuevas = res.rowCount ?? 0

      // El origen se escribe aparte y no en el INSERT de arriba, para que
      // también complete los movimientos que ya estaban: los 2822 de la base
      // real entraron antes de que estas columnas existieran. Reimportar el
      // mismo archivo no inserta nada y los rellena igual.
      await cliente.query(
        `UPDATE movimiento SET hoja = $1, fila = x.f
         FROM UNNEST($2::text[], $3::int[]) AS x(hu, f)
         WHERE movimiento.huella = x.hu`,
        [hoja.name, [...filaDe.keys()], [...filaDe.values()]])

      await cliente.query(
        'UPDATE extracto_carga SET filas_nuevas = $1, filas_duplicadas = $2 WHERE id = $3',
        [nuevas, leidas - sinFecha - nuevas, carga.id])

      resumen.push({
        cuenta: hoja.name,
        leidas,
        nuevas,
        duplicadas: leidas - sinFecha - nuevas,
        aRevisar: revisar.filter(Boolean).length,
        sinFecha,
        fechaMin,
        fechaMax,
      })
    }

    await cliente.query('COMMIT')
    return resumen
  } catch (e) {
    await cliente.query('ROLLBACK')
    throw e
  } finally {
    cliente.release()
  }
}

// ponytail: 10 líneas para poder verificar F2 hoy, sin depender de la pantalla
// de F5. Cuando exista la subida por web va a llamar a `importarExtracto` igual.
// `import.meta.main` existe desde Node 24.2, pero `@types/node` está en ^20 y
// no lo conoce. El cast es local; el arreglo de fondo es subir los tipos.
if ((import.meta as { main?: boolean }).main) {
  const ruta = process.argv[2]
  if (!ruta) {
    console.error('uso: pnpm importar <archivo.xlsx>')
    process.exit(1)
  }
  const resumen = await importarExtracto(ruta)
  console.table(resumen)
  const suma = (k: keyof ResumenCuenta) =>
    resumen.reduce((a, r) => a + (r[k] as number), 0)
  console.log(`leídas ${suma('leidas')} · nuevas ${suma('nuevas')} · ` +
    `duplicadas ${suma('duplicadas')} · a revisar ${suma('aRevisar')} · ` +
    `sin fecha ${suma('sinFecha')}`)
  await db.end()
}
