import { db } from './db.ts'
import { parsearImporte } from './extracto.ts'

/**
 * Qué fila del extracto eligió una PERSONA para un comprobante.
 *
 * `/encontrar` propone con la cascada de la empresa (nro de transacción + CUIT →
 * 90%; monto + fecha → 50%), pero cuando dos movimientos empatan no elige
 * ninguno: adivinar entre dos filas del mismo importe sería inventar. Acá se
 * guarda cuál eligió una persona.
 *
 * Guarda SOLO la elección humana. Lo que propuso el algoritmo no se guarda
 * porque es determinístico y se recalcula en cada carga; congelarlo haría que,
 * el día que se toque la cascada, la fila vieja siguiera afirmando lo que la
 * regla decía antes. La tasa de corrección sale de cruzar esto con la query.
 *
 * ⚠️ Es temporal, igual que su tabla: cuando `motor.ts` se reescriba con esta
 * cascada, las decisiones humanas pasan a `conciliacion.decidido_por = 'persona'`
 * —que ya existe y que `reconciliar()` ya respeta— y esto se borra entero.
 */

export type ResultadoEleccion = { ok: true } | { ok: false, error: string }

/** Postgres cuando se viola un índice único. */
const UNICO_VIOLADO = '23505'

/**
 * "Esta fila del extracto es la de este comprobante".
 *
 * Un movimiento no puede ser de dos comprobantes: es plata que se movió una
 * sola vez. Si ya está tomado se avisa y no se toca nada, porque pisar al
 * primero escondería justamente el error que hay que mirar.
 */
export async function elegir(
  comprobanteId: number, movimientoId: number, nota?: string,
): Promise<ResultadoEleccion> {
  try {
    await db.query(
      `INSERT INTO eleccion (comprobante_id, movimiento_id, nota)
       VALUES ($1, $2, $3)
       ON CONFLICT (comprobante_id) DO UPDATE
         SET movimiento_id = EXCLUDED.movimiento_id, nota = EXCLUDED.nota,
             elegido_en = now()`,
      [comprobanteId, movimientoId, nota ?? null])
    return { ok: true }
  } catch (e) {
    const { code } = e as { code?: string }
    if (code !== UNICO_VIOLADO) throw e
    const { rows: [otro] } = await db.query<{ comprobante_id: number, archivo: string }>(
      `SELECT e.comprobante_id, c.archivo FROM eleccion e
       JOIN comprobante c ON c.id = e.comprobante_id WHERE e.movimiento_id = $1`,
      [movimientoId])
    return {
      ok: false,
      error: `Ese movimiento ya está asignado al comprobante ${otro?.archivo ?? '?'}`
        + ` (id ${otro?.comprobante_id ?? '?'}). Una fila del extracto es de un solo`
        + ' comprobante: si los dos parecen correctos, uno de los dos está mal leído.',
    }
  }
}

/** Deshacer: el comprobante vuelve a mostrar lo que dice el algoritmo. */
export async function borrarEleccion(comprobanteId: number): Promise<void> {
  await db.query('DELETE FROM eleccion WHERE comprobante_id = $1', [comprobanteId])
}

/** Todas las elecciones, por comprobante. Se cruza contra lo que propone la query. */
export async function elegidas(): Promise<Map<number, number>> {
  const { rows } = await db.query<{ comprobante_id: number, movimiento_id: number }>(
    'SELECT comprobante_id, movimiento_id FROM eleccion')
  return new Map(rows.map((f) => [f.comprobante_id, f.movimiento_id]))
}

/** Una fila del extracto, con lo que hace falta para reconocerla en el Excel. */
export type MovimientoEncontrado = {
  id: number
  hoja: string | null
  fila: number | null
  fecha: string
  importe: string | null
  descripcion: string
  nroTransaccion: string | null
  cuitEmisor: string | null
  /** A qué comprobante ya se lo asignaron, si a alguno. */
  tomadoPor: string | null
}

export type FiltroMovimientos = {
  /** Una fila puntual, por id. Sirve para releer la que ya se eligió. */
  id?: number
  detalle?: string
  monto?: string
  fecha?: string
  /** Fecha del comprobante: ordena por cercanía en vez de por fecha a secas. */
  cerca?: string
  limite?: number
  incluirEgresos?: boolean
}

/**
 * Buscar a mano una fila del extracto, cuando la regla no encontró ninguna.
 *
 * Son 2822 movimientos: sin filtros esto sería una lista inservible, así que
 * `limite` corta y `total` dice cuántos hay de verdad. Los tres filtros se
 * combinan con AND — buscar tiene que ACHICAR, porque un buscador que devuelve
 * de más invita a dar por buena la primera fila parecida, que es exactamente el
 * error que este proyecto no puede cometer.
 *
 * El monto pasa por `parsearImporte`, el mismo del extracto: en esa columna
 * conviven el formato argentino y el estadounidense, y escribir `4.800,50` a
 * mano tiene que encontrar lo mismo que `4800.50`.
 */
export async function buscarMovimientos(
  f: FiltroMovimientos = {},
): Promise<{ filas: MovimientoEncontrado[], total: number }> {
  const cond: string[] = []
  const args: unknown[] = []
  const arg = (v: unknown) => `$${args.push(v)}`

  // Buscar por id trae esa fila y nada más, sea ingreso o egreso: se usa para
  // releer una que YA se eligió, y ahí filtrar por tipo la haría desaparecer.
  if (f.id !== undefined) cond.push(`m.id = ${arg(f.id)}`)
  else if (!f.incluirEgresos) cond.push('m.es_ingreso')
  if (f.detalle?.trim()) cond.push(`m.descripcion ILIKE ${arg(`%${f.detalle.trim()}%`)}`)
  if (f.fecha?.trim()) cond.push(`m.fecha = ${arg(f.fecha.trim())}::date`)
  if (f.monto?.trim()) {
    const { importe } = parsearImporte(f.monto)
    // Un monto que no se puede leer no puede filtrar: devolver todo sería
    // mentir sobre lo que se buscó. Se pide algo que no existe.
    cond.push(importe === null ? 'false' : `m.importe = ${arg(importe)}::numeric`)
  }

  // `cerca` no filtra: ordena. Es el default cuando la regla no encontró nada y
  // hay que ofrecer un punto de partida, no una respuesta.
  const orden = f.cerca?.trim()
    ? `abs(m.fecha - ${arg(f.cerca.trim())}::date), m.fecha DESC`
    : 'm.fecha DESC, m.id'

  const { rows } = await db.query<MovimientoEncontrado & { total: string }>(
    `SELECT m.id, m.hoja, m.fila, to_char(m.fecha,'YYYY-MM-DD') AS fecha,
            m.importe, m.descripcion, m.nro_transaccion AS "nroTransaccion",
            m.cuit_emisor AS "cuitEmisor", c.archivo AS "tomadoPor",
            count(*) OVER () AS total
     FROM movimiento m
     LEFT JOIN eleccion e ON e.movimiento_id = m.id
     LEFT JOIN comprobante c ON c.id = e.comprobante_id
     ${cond.length ? `WHERE ${cond.join(' AND ')}` : ''}
     ORDER BY ${orden}
     LIMIT ${arg(f.limite ?? 50)}`,
    args)

  return { filas: rows, total: rows.length ? Number(rows[0].total) : 0 }
}

/** Un movimiento que la cascada propone para un comprobante. */
export type CandidatoFila = MovimientoEncontrado & {
  comprobanteId: number
  regla: '90' | '50'
  /** Días entre el movimiento y el comprobante. 0 = mismo día. */
  dias: number
}

/**
 * La cascada de la empresa, en SQL. **Vive acá y en ningún otro lado.**
 *
 *   1. nro de transacción + CUIT coinciden → 90%
 *   2. si no, monto y fecha                → 50%
 *
 * La usan la lista de /encontrar y la pantalla de a uno. Tenerla escrita dos
 * veces garantizaba que el día que se toque una, la otra siga diciendo lo
 * contrario y nadie se entere hasta que un comprobante quede mal asignado.
 *
 * Los sintéticos quedan afuera: sus montos los inventó un script y no pueden
 * cruzar con un extracto real.
 */
export async function candidatos(comprobanteId?: number): Promise<CandidatoFila[]> {
  const { rows } = await db.query<CandidatoFila>(
    `WITH c AS (
       SELECT id, monto, fecha, referencia,
              -- El CUIT se compara por sus DÍGITOS. El extracto lo trae sin
              -- separadores (2586 de 2586) y una persona lo escribe con guiones
              -- en /revisar (33 de 42): comparar los textos tal cual dejaba 33
              -- comprobantes sin poder cruzar nunca. Medido el 2026-08-11: el
              -- cruce por CUIT pasa de 8 a 40 con este solo cambio.
              nullif(regexp_replace(coalesce(cuit_emisor,''), '\\D', '', 'g'), '') AS cuit
       FROM comprobante
       WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico'
         AND ($1::int IS NULL OR id = $1)
     ),
     m AS (
       SELECT *, nullif(regexp_replace(coalesce(cuit_emisor,''), '\\D', '', 'g'), '') AS cuit
       FROM movimiento
     ),
     -- Escalón 1 · lower() a los dos lados: el nro de transacción puede traer
     -- letras y la IA las transcribe como las ve.
     r1 AS (
       SELECT c.id AS comp, m.id AS mov, '90'::text AS regla
       FROM c JOIN m
         ON lower(m.nro_transaccion) = lower(c.referencia) AND m.cuit = c.cuit
       WHERE c.referencia IS NOT NULL AND c.cuit IS NOT NULL
     ),
     -- Escalón 2 · el CUIT, el importe y el día, los tres a la vez. Son datos
     -- independientes entre sí: que coincidan por casualidad los tres es mucho
     -- menos probable que un choque de importe, así que vale lo mismo que el
     -- escalón 1. En el extracto real el nro de transacción casi nunca coincide
     -- con la referencia del comprobante, y sin este escalón 23 comprobantes con
     -- los tres datos idénticos quedaban en 50% o sin encontrar.
     r2 AS (
       SELECT c.id AS comp, m.id AS mov, '90'::text AS regla
       FROM c JOIN m
         ON m.cuit = c.cuit AND m.importe = c.monto AND m.fecha = c.fecha
       WHERE c.cuit IS NOT NULL AND c.monto IS NOT NULL AND c.fecha IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM r1 WHERE r1.comp = c.id)
     ),
     -- Escalón 3 · sin CUIT que lo respalde, un importe y un día que coinciden
     -- son eso y nada más: pueden ser casualidad.
     r3 AS (
       SELECT c.id AS comp, m.id AS mov, '50'::text AS regla
       FROM c JOIN m
         ON m.importe = c.monto AND m.fecha = c.fecha AND m.es_ingreso
       WHERE c.monto IS NOT NULL AND c.fecha IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM r1 WHERE r1.comp = c.id)
         AND NOT EXISTS (SELECT 1 FROM r2 WHERE r2.comp = c.id)
     ),
     todos AS (
       SELECT * FROM r1 UNION ALL SELECT * FROM r2 UNION ALL SELECT * FROM r3
     )
     SELECT t.comp AS "comprobanteId", t.regla, m.id, m.hoja, m.fila,
            to_char(m.fecha,'YYYY-MM-DD') AS fecha, m.importe, m.descripcion,
            m.nro_transaccion AS "nroTransaccion", m.cuit_emisor AS "cuitEmisor",
            tc.archivo AS "tomadoPor", m.fecha - c.fecha AS dias
     FROM todos t
     JOIN c ON c.id = t.comp
     JOIN movimiento m ON m.id = t.mov
     LEFT JOIN eleccion e ON e.movimiento_id = m.id
     LEFT JOIN comprobante tc ON tc.id = e.comprobante_id
     ORDER BY t.comp, t.regla, m.fecha`,
    [comprobanteId ?? null])
  return rows
}
