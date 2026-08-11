import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { rm } from 'node:fs/promises'
import ExcelJS from 'exceljs'
import { db } from './db.ts'
import { importarExtracto, type ResumenCuenta } from './importar.ts'

// Un .xlsx chico con la respuesta conocida. Tiene lo mismo que el archivo real
// —dos formatos de número, una fila repetida, una vacía, una celda ilegible—
// pero en 13 filas que se pueden verificar una por una.
//
// Se genera acá y no se commitea: un binario en el repo se desincroniza del
// test que lo usa. Corre contra `conciliador_test`, nunca contra la base real.

const RUTA = join(tmpdir(), `extracto-prueba-${process.pid}.xlsx`)
const F = (dia: number) => new Date(Date.UTC(2026, 5, dia))
const COELSA_A = 'AAAA1111BBBB2222CCCC33'
const COELSA_B = 'BBBB2222CCCC3333DDDD44'

const FILA_1 = [F(1), 111, `ING TRANSF:${COELSA_A} 27123456789 GOMEZ/A`, '$ 368.500,00', '$ 1,00']

async function generarExcel() {
  const wb = new ExcelJS.Workbook()
  const encabezado = ['FECHA', 'NRO TRANSACCION', 'DESCRIPCION', 'IMPORTE', 'SALDO']

  const sucesion = wb.addWorksheet('SUCESION')
  sucesion.addRow(encabezado)
  sucesion.addRow(FILA_1)                                                    // AR
  sucesion.addRow([F(2), 222, 'ING TRANSF 20111222333 PEREZ, J', '$ 16,000.00', '$ 2,00'])  // US
  sucesion.addRow([F(3), 333, 'MOVISTAR FACTURA', '-$ 112,340.06', '$ 3,00'])  // egreso
  sucesion.addRow([F(4), 444, 'TEF DEPOSITO', '$ 1,50', '$ 4,00'])           // un separador
  sucesion.addRow([F(5), 555, 'TEF DEPOSITO', '$ 1.500', '$ 5,00'])          // AMBIGUO
  sucesion.addRow([F(8), 666, 'ING TRANSF 30555666777 SRL', '$ 5.094.237,85', '$ 6,00'])
  sucesion.addRow([F(9), 777, 'TEF DEPOSITO', '############', '$ 7,00'])     // AMBIGUO
  sucesion.addRow(FILA_1)                                                    // repetida
  sucesion.addRow(['', '', '', '', '$ 8,00'])                                // solo SALDO
  sucesion.addRow([F(10), 888, 'CAPITALIZACION', '$ 250000', '$ 9,00'])      // sin separador

  const quique = wb.addWorksheet('QUIQUE')
  quique.addRow(encabezado)
  quique.addRow([F(5), 901, 'TEF DEPOSITO', '$ 99.999,99', '$ 1,00'])
  quique.addRow([F(6), 902, 'AFIP PAGO', '$ -45.000,00', '$ 2,00'])          // signo tras el $
  quique.addRow([F(9), 903, 'ING TRANSF 23777888999 X', '$ 1.234.567', '$ 3,00'])  // dos puntos
  quique.addRow([F(10), 904, `CREDIN:${COELSA_B} 30555666777 SRL`, '$ 12.000,00', '$ 4,00'])

  await wb.xlsx.writeFile(RUTA)
}

const porCuenta = (r: ResumenCuenta[], nombre: string) =>
  r.find((x) => x.cuenta === nombre)!

/** De qué hoja y fila del Excel salió un movimiento. */
async function origen(nro: string) {
  const { rows } = await db.query(
    'SELECT hoja, fila FROM movimiento WHERE nro_transaccion = $1', [nro])
  return rows[0]
}

/** Una fila de `movimiento`, con la fecha y el importe ya como texto. */
async function movimiento(nro: string) {
  const { rows } = await db.query(
    `SELECT to_char(fecha, 'YYYY-MM-DD') AS fecha, importe, es_ingreso,
            requiere_revision, cuit_emisor, coelsa_id, tipo
     FROM movimiento WHERE nro_transaccion = $1`, [nro])
  return rows[0]
}

let resumen: ResumenCuenta[]

before(async () => {
  await db.query('TRUNCATE movimiento, extracto_carga RESTART IDENTITY CASCADE')
  await generarExcel()
  resumen = await importarExtracto(RUTA)
})

after(async () => {
  await rm(RUTA, { force: true })
  await db.end()
})

// ─── El resumen ────────────────────────────────────────────────────────

test('la hoja con la fila repetida y la vacía cuenta bien', () => {
  const s = porCuenta(resumen, 'SUCESION')
  assert.equal(s.leidas, 9, 'la fila con solo SALDO no debería contarse')
  assert.equal(s.nuevas, 8, 'la fila repetida no debería entrar')
  assert.equal(s.duplicadas, 1)
  assert.equal(s.sinFecha, 0)
})

test('las dos filas de importe irresoluble quedan para revisar', () => {
  assert.equal(porCuenta(resumen, 'SUCESION').aRevisar, 2)
})

test('la segunda hoja entra completa', () => {
  const q = porCuenta(resumen, 'QUIQUE')
  assert.deepEqual(
    { leidas: q.leidas, nuevas: q.nuevas, duplicadas: q.duplicadas, aRevisar: q.aRevisar },
    { leidas: 4, nuevas: 4, duplicadas: 0, aRevisar: 0 })
})

test('la cobertura de cada cuenta queda registrada', () => {
  const s = porCuenta(resumen, 'SUCESION')
  assert.equal(s.fechaMin, '2026-06-01')
  assert.equal(s.fechaMax, '2026-06-10')
  const q = porCuenta(resumen, 'QUIQUE')
  assert.equal(q.fechaMin, '2026-06-05')
  assert.equal(q.fechaMax, '2026-06-10')
})

// ─── Los importes, uno por uno ─────────────────────────────────────────

test('el formato argentino no se lee como centavos', async () => {
  assert.equal((await movimiento('111')).importe, '368500.00')
})

test('el formato estadounidense se lee bien en la misma columna', async () => {
  assert.equal((await movimiento('222')).importe, '16000.00')
})

test('un egreso entra en negativo y marcado como egreso', async () => {
  const m = await movimiento('333')
  assert.equal(m.importe, '-112340.06')
  assert.equal(m.es_ingreso, false)
})

test('el signo después del símbolo también es un egreso', async () => {
  const m = await movimiento('902')
  assert.equal(m.importe, '-45000.00')
  assert.equal(m.es_ingreso, false)
})

test('un separador con dos dígitos detrás es un decimal', async () => {
  assert.equal((await movimiento('444')).importe, '1.50')
})

test('varios separadores de miles no se confunden con decimales', async () => {
  assert.equal((await movimiento('666')).importe, '5094237.85')
  assert.equal((await movimiento('903')).importe, '1234567.00')
})

test('un importe sin separadores entra tal cual', async () => {
  assert.equal((await movimiento('888')).importe, '250000.00')
})

test('un importe irresoluble queda en NULL y marcado, nunca adivinado', async () => {
  for (const nro of ['555', '777']) {
    const m = await movimiento(nro)
    assert.equal(m.importe, null, `el importe de la fila ${nro} se adivinó`)
    assert.equal(m.requiere_revision, true)
  }
})

// ─── Lo extraído de la descripción ─────────────────────────────────────

test('el COELSA se extrae de TRANSF: y de CREDIN:', async () => {
  assert.equal((await movimiento('111')).coelsa_id, COELSA_A)
  assert.equal((await movimiento('904')).coelsa_id, COELSA_B)
})

test('el CUIT y el tipo salen de la descripción', async () => {
  const m = await movimiento('111')
  assert.equal(m.cuit_emisor, '27123456789')
  assert.equal(m.tipo, 'ING TRANSF')
})

test('sin COELSA la columna queda en NULL, no en string vacío', async () => {
  assert.equal((await movimiento('444')).coelsa_id, null)
})

test('la fecha sobrevive al ida y vuelta por el Excel', async () => {
  assert.equal((await movimiento('111')).fecha, '2026-06-01')
})

// ─── De dónde salió cada movimiento ────────────────────────────────────

test('cada movimiento sabe de qué hoja y fila del Excel salió', async () => {
  assert.deepEqual(await origen('111'), { hoja: 'SUCESION', fila: 2 })
  assert.deepEqual(await origen('904'), { hoja: 'QUIQUE', fila: 5 })
})

test('la fila es la del Excel, no la posición en la base', async () => {
  // `888` está en la fila 11: antes vienen la repetida (9, que no entra por la
  // huella UNIQUE) y la que solo trae SALDO (10, que se saltea). Es el octavo
  // movimiento de SUCESION en la base, así que contar filas daría 9.
  // Ese desvío es el que hacía que /encontrar mostrara una fila equivocada.
  assert.deepEqual(await origen('888'), { hoja: 'SUCESION', fila: 11 })
})

test('reimportar rellena el origen de los movimientos que ya estaban', async () => {
  // El camino que usa la base real: los 2822 movimientos entraron sin estas
  // columnas y se completan volviendo a leer el Excel, sin borrar nada.
  await db.query('UPDATE movimiento SET hoja = NULL, fila = NULL')
  await importarExtracto(RUTA)
  const { rows: [{ huerfanos }] } = await db.query<{ huerfanos: number }>(
    'SELECT count(*)::int AS huerfanos FROM movimiento WHERE fila IS NULL')
  assert.equal(huerfanos, 0, 'quedaron movimientos sin saber de qué fila salieron')
  assert.deepEqual(await origen('888'), { hoja: 'SUCESION', fila: 11 })
})

// ─── Reimportar ────────────────────────────────────────────────────────

test('importar desde un Buffer da lo mismo que desde una ruta', async () => {
  // Es el camino que usa la subida por web: el archivo nunca toca el disco.
  const { readFile } = await import('node:fs/promises')
  const desdeBuffer = await importarExtracto(await readFile(RUTA), 'subido.xlsx')
  assert.equal(porCuenta(desdeBuffer, 'SUCESION').leidas, 9)
  assert.equal(porCuenta(desdeBuffer, 'SUCESION').nuevas, 0, 'ya estaban: no debería duplicar')

  const { rows: [{ archivo }] } = await db.query<{ archivo: string }>(
    `SELECT archivo FROM extracto_carga ORDER BY id DESC LIMIT 1`)
  assert.equal(archivo, 'subido.xlsx', 'el nombre que manda la web tiene que quedar registrado')
})

test('reimportar el mismo archivo no inserta nada', async () => {
  const segunda = await importarExtracto(RUTA)
  assert.equal(porCuenta(segunda, 'SUCESION').nuevas, 0)
  assert.equal(porCuenta(segunda, 'QUIQUE').nuevas, 0)

  const { rows: [{ total }] } = await db.query<{ total: string }>(
    'SELECT count(*)::int AS total FROM movimiento')
  assert.equal(total, 12, 'la segunda importación cambió el total')
})
