import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { db } from './db.ts'

after(() => db.end())

// El test de F1: el doble cobro tiene que ser imposible por diseño, no por
// disciplina del código. Corre dentro de una transacción que se revierte, así
// que no deja nada en la base.
test('la base rechaza que dos comprobantes reclamen el mismo movimiento', async () => {
  const c = await db.connect()
  try {
    await c.query('BEGIN')

    const { rows: [cuenta] } = await c.query(
      `INSERT INTO cuenta (nombre) VALUES ('TEST') RETURNING id`)
    const { rows: [carga] } = await c.query(
      `INSERT INTO extracto_carga (cuenta_id, archivo, hash_archivo,
         filas_leidas, filas_nuevas, filas_duplicadas)
       VALUES ($1, 'test.xlsx', 'hash', 1, 1, 0) RETURNING id`, [cuenta.id])
    const { rows: [movimiento] } = await c.query(
      `INSERT INTO movimiento (cuenta_id, carga_id, fecha, descripcion,
         importe_crudo, importe, es_ingreso, huella)
       VALUES ($1, $2, '2026-06-02', 'ING TRANSF', '$ 250.000,00', 250000.00,
               TRUE, 'huella-test') RETURNING id`, [cuenta.id, carga.id])

    const nuevoComprobante = async (hash: string) => {
      const { rows: [r] } = await c.query(
        `INSERT INTO comprobante (archivo, hash_imagen) VALUES ($1, $2) RETURNING id`,
        [`${hash}.jpeg`, hash])
      return r.id
    }
    const reclamar = (comprobanteId: number) => c.query(
      `INSERT INTO conciliacion (comprobante_id, movimiento_id, estado, confianza)
       VALUES ($1, $2, 'verificado', 'alta')`, [comprobanteId, movimiento.id])

    await reclamar(await nuevoComprobante('imagen-a'))

    const segundo = await nuevoComprobante('imagen-b')
    await assert.rejects(
      () => reclamar(segundo),
      (e: { constraint?: string }) => e.constraint === 'conciliacion_movimiento_unico',
      'el segundo comprobante logró reclamar un movimiento ya reclamado')
  } finally {
    await c.query('ROLLBACK')
    c.release()
  }
})

// Las 29 filas de importe ambiguo no se adivinan: quedan sin importe y
// marcadas. Lo que no puede pasar es que quede sin importe y sin marcar.
test('la base rechaza un movimiento sin importe que no esté marcado para revisar', async () => {
  const c = await db.connect()
  try {
    await c.query('BEGIN')
    const { rows: [cuenta] } = await c.query(
      `INSERT INTO cuenta (nombre) VALUES ('TEST2') RETURNING id`)
    const { rows: [carga] } = await c.query(
      `INSERT INTO extracto_carga (cuenta_id, archivo, hash_archivo,
         filas_leidas, filas_nuevas, filas_duplicadas)
       VALUES ($1, 'test.xlsx', 'hash', 1, 1, 0) RETURNING id`, [cuenta.id])

    await assert.rejects(
      () => c.query(
        `INSERT INTO movimiento (cuenta_id, carga_id, fecha, descripcion,
           importe_crudo, importe, es_ingreso, requiere_revision, huella)
         VALUES ($1, $2, '2026-06-02', 'ING TRANSF', '$ 1.500', NULL,
                 TRUE, FALSE, 'huella-ambigua')`, [cuenta.id, carga.id]),
      (e: { constraint?: string }) => e.constraint === 'importe_nulo_solo_si_se_revisa')
  } finally {
    await c.query('ROLLBACK')
    c.release()
  }
})
