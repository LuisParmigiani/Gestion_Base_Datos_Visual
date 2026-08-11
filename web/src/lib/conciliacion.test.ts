import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { db } from './db.ts'
import { reconciliar, resolverAmbiguo, tablero, sinComprobante } from './conciliacion.ts'
import { CUENTAS, MOVIMIENTOS, COMPROBANTES } from './fixtures.ts'

// El puente entre el motor y la base. Lo que se prueba acá no es la cascada
// —eso es motor.test.ts— sino que lo que el motor decide llegue entero a la
// base: que un duplicado no rompa el índice único, que reconciliar dos veces
// no apile filas, y que una decisión humana sobreviva al recálculo.

before(async () => {
  await db.query('TRUNCATE conciliacion, comprobante, movimiento, extracto_carga, cuenta ' +
    'RESTART IDENTITY CASCADE')

  for (const c of CUENTAS) {
    const { rows: [cuenta] } = await db.query<{ id: number }>(
      'INSERT INTO cuenta (nombre, cbu) VALUES ($1, $2) RETURNING id', [c.nombre, c.cbu])
    if (c.fechaMin === null) continue
    await db.query(
      `INSERT INTO extracto_carga (cuenta_id, archivo, hash_archivo, filas_leidas,
         filas_nuevas, filas_duplicadas, fecha_min, fecha_max)
       VALUES ($1, 'fixture.xlsx', 'hash', 0, 0, 0, $2, $3)`,
      [cuenta.id, c.fechaMin, c.fechaMax])
  }

  for (const m of MOVIMIENTOS) {
    await db.query(
      `INSERT INTO movimiento (id, cuenta_id, carga_id, fecha, descripcion, importe_crudo,
         importe, es_ingreso, cuit_emisor, coelsa_id, huella)
       SELECT $1, c.id, e.id, $3, $4, $5, $6, $7, $8, $9, $10
       FROM cuenta c JOIN extracto_carga e ON e.cuenta_id = c.id WHERE c.nombre = $2`,
      [m.id, m.cuenta, m.fecha, m.descripcion, m.importe, m.importe, m.esIngreso,
       m.cuitEmisor, m.coelsaId, `huella-${m.id}`])
  }

  for (const c of COMPROBANTES) {
    await db.query(
      `INSERT INTO comprobante (id, archivo, hash_imagen, monto, fecha, cuit_emisor,
         cbu_cvu_receptor, coelsa_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
      [c.id, `c${c.id}.jpeg`, `hash-${c.id}`, c.monto, c.fecha, c.cuitEmisor,
       c.cbuReceptor, c.coelsaId])
  }

  // Las fixtures traen ids explícitos, así que las secuencias quedaron atrás.
  // Sin esto, el próximo INSERT que use el serial choca contra la clave primaria.
  for (const t of ['cuenta', 'extracto_carga', 'movimiento', 'comprobante']) {
    await db.query(
      `SELECT setval(pg_get_serial_sequence($1, 'id'), coalesce(max(id), 1)) FROM ${t}`, [t])
  }
})

after(() => db.end())

test('reconciliar guarda un veredicto por comprobante', async () => {
  const r = await reconciliar()
  assert.equal(r.recalculados, COMPROBANTES.length)
  const { rows: [{ n }] } = await db.query<{ n: number }>(
    'SELECT count(*)::int AS n FROM conciliacion')
  assert.equal(n, COMPROBANTES.length)
})

test('los estados guardados coinciden con los esperados por las fixtures', async () => {
  const filas = await tablero()
  for (const c of COMPROBANTES) {
    const fila = filas.find((f) => f.comprobanteId === c.id)
    assert.equal(fila?.estado, c.estadoEsperado, `el comprobante ${c.id} quedó mal`)
  }
})

test('un duplicado no rompe el índice único que impide el doble cobro', async () => {
  // Los dos apuntan al mismo movimiento. Si el motor guardara `movimiento_id`
  // en los dos, la base rechazaría el segundo.
  const { rows } = await db.query<{ movimiento_pretendido: number; movimiento_id: number }>(
    `SELECT movimiento_id, movimiento_pretendido FROM conciliacion WHERE estado = 'duplicado'`)
  assert.equal(rows.length, 2)
  for (const r of rows) {
    assert.equal(r.movimiento_id, null, 'un duplicado no puede quedarse el movimiento')
    assert.equal(r.movimiento_pretendido, 7, 'pero sí tiene que decir con cuál chocó')
  }
})

test('un ambiguo guarda sus candidatos', async () => {
  const { rows: [fila] } = await db.query<{ candidatos: number[] }>(
    `SELECT candidatos FROM conciliacion WHERE estado = 'ambiguo'`)
  assert.deepEqual([...fila.candidatos].sort(), [5, 6])
})

test('reconciliar dos veces no apila filas', async () => {
  await reconciliar()
  const { rows: [{ n }] } = await db.query<{ n: number }>(
    'SELECT count(*)::int AS n FROM conciliacion')
  assert.equal(n, COMPROBANTES.length)
})

test('los ingresos que nadie reclama se listan, sin los candidatos del ambiguo', async () => {
  const filas = await sinComprobante()
  assert.deepEqual(filas.map((f) => f.id).sort((a, b) => a - b), [8, 10])
})

test('el tablero filtra por estado', async () => {
  const filas = await tablero({ estado: 'no_verificable' })
  assert.ok(filas.length > 0)
  assert.ok(filas.every((f) => f.estado === 'no_verificable'))
})

// ─── Lo que hace que resolver a mano sirva de algo ─────────────────────

test('resolver un ambiguo lo deja verificado y decidido por una persona', async () => {
  await resolverAmbiguo(5, 6)
  const { rows: [fila] } = await db.query<{ estado: string; movimiento_id: number; decidido_por: string }>(
    'SELECT estado, movimiento_id, decidido_por FROM conciliacion WHERE comprobante_id = 5')
  assert.equal(fila.estado, 'verificado')
  assert.equal(fila.movimiento_id, 6)
  assert.equal(fila.decidido_por, 'persona')
})

test('no se puede resolver eligiendo un movimiento que no era candidato', async () => {
  await assert.rejects(() => resolverAmbiguo(5, 999))
})

test('recalcular NO pisa lo que decidió una persona', async () => {
  const r = await reconciliar()
  assert.equal(r.respetados, 1)
  const { rows: [fila] } = await db.query<{ estado: string; decidido_por: string }>(
    'SELECT estado, decidido_por FROM conciliacion WHERE comprobante_id = 5')
  assert.equal(fila.estado, 'verificado', 'el motor volvió a marcarlo ambiguo')
  assert.equal(fila.decidido_por, 'persona')
})

test('el movimiento elegido a mano deja de figurar como sin comprobante', async () => {
  const filas = await sinComprobante()
  assert.equal(filas.some((f) => f.id === 6), false)
  // El 5 era el otro candidato: ahora que nadie lo reclama, sí falta su comprobante.
  assert.equal(filas.some((f) => f.id === 5), true)
})
