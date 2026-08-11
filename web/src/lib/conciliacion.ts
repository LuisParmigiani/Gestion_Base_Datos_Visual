import { db } from './db.ts'
import { conciliar, type Comprobante, type Movimiento, type Cuenta } from './motor.ts'

/**
 * El puente entre el motor —que es lógica pura— y la base.
 *
 * Carga, corre la cascada, guarda. **No vuelve a decidir lo que decidió una
 * persona:** los veredictos con `decidido_por = 'persona'` se dejan como están.
 * Si el motor pudiera pisarlos, resolver un ambiguo a mano no serviría de nada.
 */
export async function reconciliar(): Promise<{ recalculados: number; respetados: number }> {
  const { rows: cuentas } = await db.query<Cuenta>(
    `SELECT c.nombre, c.cbu,
            to_char(min(e.fecha_min), 'YYYY-MM-DD') AS "fechaMin",
            to_char(max(e.fecha_max), 'YYYY-MM-DD') AS "fechaMax"
     FROM cuenta c LEFT JOIN extracto_carga e ON e.cuenta_id = c.id
     WHERE c.activa GROUP BY c.nombre, c.cbu`)

  const { rows: movimientos } = await db.query<Movimiento>(
    `SELECT m.id, c.nombre AS cuenta, to_char(m.fecha, 'YYYY-MM-DD') AS fecha,
            m.importe, m.es_ingreso AS "esIngreso",
            m.cuit_emisor AS "cuitEmisor", m.coelsa_id AS "coelsaId"
     FROM movimiento m JOIN cuenta c ON c.id = m.cuenta_id`)

  // Los que ya decidió una persona quedan afuera del recálculo.
  const { rows: comprobantes } = await db.query<Comprobante>(
    `SELECT co.id, co.monto, to_char(co.fecha, 'YYYY-MM-DD') AS fecha,
            co.cuit_emisor AS "cuitEmisor", co.cbu_cvu_receptor AS "cbuReceptor",
            co.coelsa_id AS "coelsaId"
     FROM comprobante co
     LEFT JOIN conciliacion cc ON cc.comprobante_id = co.id
     WHERE cc.id IS NULL OR cc.decidido_por <> 'persona'`)

  const { rows: [{ respetados }] } = await db.query<{ respetados: number }>(
    `SELECT count(*)::int AS respetados FROM conciliacion WHERE decidido_por = 'persona'`)

  if (comprobantes.length === 0) return { recalculados: 0, respetados }

  const { veredictos } = conciliar(comprobantes, movimientos, cuentas)

  const cliente = await db.connect()
  try {
    await cliente.query('BEGIN')
    for (const [comprobanteId, v] of veredictos) {
      // Un `duplicado` no puede quedarse el movimiento: el índice único de F1
      // lo impide a propósito. Lo declara en `movimiento_pretendido`.
      const esDuplicado = v.estado === 'duplicado'
      await cliente.query(
        `INSERT INTO conciliacion
           (comprobante_id, movimiento_id, movimiento_pretendido, estado,
            confianza, regla, candidatos, decidido_por, decidido_en)
         VALUES ($1, $2, $3, $4, $5, $6, $7, 'motor', now())
         ON CONFLICT (comprobante_id) DO UPDATE SET
           movimiento_id = EXCLUDED.movimiento_id,
           movimiento_pretendido = EXCLUDED.movimiento_pretendido,
           estado = EXCLUDED.estado, confianza = EXCLUDED.confianza,
           regla = EXCLUDED.regla, candidatos = EXCLUDED.candidatos,
           decidido_por = 'motor', decidido_en = now()`,
        [comprobanteId, esDuplicado ? null : v.movimientoId,
         esDuplicado ? v.movimientoId : null, v.estado,
         v.confianza, v.regla, v.candidatos])
    }
    await cliente.query('COMMIT')
  } catch (e) {
    await cliente.query('ROLLBACK')
    throw e
  } finally {
    cliente.release()
  }

  return { recalculados: veredictos.size, respetados }
}

/** Una persona elige uno de los candidatos de un ambiguo. */
export async function resolverAmbiguo(comprobanteId: number, movimientoId: number) {
  const { rowCount } = await db.query(
    `UPDATE conciliacion
     SET movimiento_id = $2, estado = 'verificado', confianza = 'media',
         regla = NULL, candidatos = '{}', decidido_por = 'persona', decidido_en = now()
     WHERE comprobante_id = $1 AND estado = 'ambiguo' AND $2 = ANY(candidatos)`,
    [comprobanteId, movimientoId])
  if (rowCount === 0) {
    throw new Error(
      `El movimiento ${movimientoId} no es candidato del comprobante ${comprobanteId}`)
  }
}

export type FilaTablero = {
  comprobanteId: number
  archivo: string
  cuenta: string | null
  monto: string | null
  fecha: string | null
  estado: string
  confianza: string | null
  decididoPor: string
  movimientoId: number | null
  candidatos: number[]
}

/** El tablero: un comprobante por fila, con su veredicto. */
export async function tablero(filtro: { estado?: string; cuenta?: string } = {}) {
  const { rows } = await db.query<FilaTablero>(
    `SELECT co.id AS "comprobanteId", co.archivo, cu.nombre AS cuenta, co.monto,
            to_char(co.fecha, 'YYYY-MM-DD') AS fecha,
            cc.estado, cc.confianza, cc.decidido_por AS "decididoPor",
            coalesce(cc.movimiento_id, cc.movimiento_pretendido) AS "movimientoId",
            cc.candidatos
     FROM comprobante co
     JOIN conciliacion cc ON cc.comprobante_id = co.id
     LEFT JOIN cuenta cu ON cu.cbu = co.cbu_cvu_receptor
     WHERE ($1::text IS NULL OR cc.estado = $1)
       AND ($2::text IS NULL OR cu.nombre = $2)
     ORDER BY co.fecha DESC NULLS LAST, co.id DESC`,
    [filtro.estado ?? null, filtro.cuenta ?? null])
  return rows
}

/** Ingresos que ningún comprobante reclama: el sexto estado. */
export async function sinComprobante(cuenta?: string) {
  const { rows } = await db.query(
    `SELECT m.id, c.nombre AS cuenta, to_char(m.fecha, 'YYYY-MM-DD') AS fecha,
            m.importe, m.descripcion
     FROM movimiento m
     JOIN cuenta c ON c.id = m.cuenta_id
     WHERE m.es_ingreso
       -- Un movimiento reclamado, disputado por dos duplicados, o candidato de
       -- un ambiguo, NO es "sin comprobante": alguien lo está reclamando.
       AND NOT EXISTS (
         SELECT 1 FROM conciliacion cc
         WHERE cc.movimiento_id = m.id
            OR cc.movimiento_pretendido = m.id
            OR m.id = ANY(cc.candidatos))
       AND ($1::text IS NULL OR c.nombre = $1)
     ORDER BY m.fecha DESC, m.id DESC`,
    [cuenta ?? null])
  return rows
}
