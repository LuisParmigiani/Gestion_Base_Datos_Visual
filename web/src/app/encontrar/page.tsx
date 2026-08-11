import Link from 'next/link'
import { db } from '@/lib/db'
import { plata } from '../estados'

export const dynamic = 'force-dynamic'

/**
 * Qué fila del extracto le corresponde a cada comprobante, y por qué.
 *
 * No usa `motor.ts`: aquél cruza por `cuenta.cbu`, que está en NULL en las tres
 * cuentas, así que daría "no verificable" en los 52. Esta pantalla implementa
 * la cascada que describió la empresa, que **no necesita los CBU**:
 *
 *   1. nro de transacción + CUIT coinciden → se chequea monto y fecha → 90%
 *   2. si no, solo monto y fecha                                      → 50%
 *
 * Es una pantalla de diagnóstico, no el veredicto: sirve para ver dónde acierta
 * y dónde no, y para que una persona busque a mano los que no aparecieron.
 */

type Fila = {
  id: number
  archivo: string
  monto: string | null
  fecha: string | null
  cuitEmisor: string | null
  referencia: string | null
  revisado: boolean
  regla: '90' | '50' | null
  candidatos: number
  movId: number | null
  hoja: string | null
  movFecha: string | null
  movImporte: string | null
  movNro: string | null
  movCuit: string | null
  movDescripcion: string | null
  filaExcel: number | null
}

export default async function Encontrar() {
  const { rows } = await db.query<Fila>(
    `WITH c AS (
       SELECT id, archivo, monto, fecha, cuit_emisor, referencia,
              revisado_en IS NOT NULL AS revisado
       FROM comprobante WHERE corrida_base IS NOT NULL
     ),
     -- Escalón 1: el número de transacción Y el CUIT coinciden.
     -- lower() a los dos lados: el nro de transacción puede traer letras y la
     -- IA las transcribe como las ve. Hoy no cambia ningún resultado —ninguna
     -- fila del extracto tiene letras— pero es el join del que depende el 90%.
     r1 AS (
       SELECT c.id AS comp, m.id AS mov, '90'::text AS regla
       FROM c JOIN movimiento m
         ON lower(m.nro_transaccion) = lower(c.referencia)
        AND m.cuit_emisor = c.cuit_emisor
       WHERE c.referencia IS NOT NULL AND c.cuit_emisor IS NOT NULL
     ),
     -- Escalón 2: monto y fecha, para los que no resolvió el escalón 1.
     r2 AS (
       SELECT c.id AS comp, m.id AS mov, '50'::text AS regla
       FROM c JOIN movimiento m
         ON m.importe = c.monto AND m.fecha = c.fecha AND m.es_ingreso
       WHERE c.monto IS NOT NULL AND c.fecha IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM r1 WHERE r1.comp = c.id)
     ),
     todos AS (SELECT * FROM r1 UNION ALL SELECT * FROM r2),
     -- Un solo candidato = se puede señalar. Varios = ambiguo, no se elige.
     resumen AS (
       SELECT comp, min(regla) AS regla, count(*) AS candidatos,
              CASE WHEN count(*) = 1 THEN min(mov) END AS mov
       FROM todos GROUP BY comp
     )
     SELECT c.id, c.archivo, c.monto, to_char(c.fecha,'YYYY-MM-DD') AS fecha,
            c.cuit_emisor AS "cuitEmisor", c.referencia, c.revisado,
            s.regla, coalesce(s.candidatos,0) AS candidatos,
            m.id AS "movId", m.hoja,
            to_char(m.fecha,'YYYY-MM-DD') AS "movFecha", m.importe AS "movImporte",
            m.nro_transaccion AS "movNro", m.cuit_emisor AS "movCuit",
            m.descripcion AS "movDescripcion",
            -- La hoja y la fila las guarda el importador leyendo el .xlsx, así
            -- que son la fila exacta. Antes se estimaban contando movimientos y
            -- eso se corría un lugar por cada fila repetida que la base descarta.
            m.fila AS "filaExcel"
     FROM c
     LEFT JOIN resumen s ON s.comp = c.id
     LEFT JOIN movimiento m ON m.id = s.mov
     LEFT JOIN cuenta cu ON cu.id = m.cuenta_id
     ORDER BY (s.regla IS NULL) DESC, s.regla, c.id`)

  const con90 = rows.filter((r) => r.regla === '90').length
  const con50 = rows.filter((r) => r.regla === '50').length
  const sin = rows.filter((r) => !r.regla).length

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Revisión de encontrados</h1>
        <p className="mt-2 max-w-3xl text-sm text-stone-600">
          Qué fila del extracto le corresponde a cada comprobante y por qué regla.
          Los que no aparecieron van primero: buscalos a mano en el Excel y, si los
          encontrás, avisá con qué dato — eso dice qué le falta a la regla.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 text-sm">
        <span className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5">
          <strong>{con90}</strong> por nro de transacción + CUIT · 90%
        </span>
        <span className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5">
          <strong>{con50}</strong> por monto + fecha · 50%
        </span>
        <span className="rounded border border-stone-300 bg-white px-3 py-1.5">
          <strong>{sin}</strong> sin encontrar
        </span>
      </div>

      {/* El export es un GET a mano y no una Server Action: lo que devuelve es
          un archivo para descargar, no una navegación. El navegador ya sabe
          hacer esto con un <form method="get">, sin una línea de JavaScript. */}
      <form action="/api/exportar" method="get"
            className="flex flex-wrap items-end gap-3 rounded border border-stone-300 bg-stone-50 px-4 py-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-stone-600">Qué exportar</span>
          <select name="que" defaultValue="comprobantes"
                  className="rounded border border-stone-300 bg-white px-2 py-1.5">
            <option value="comprobantes">Comprobantes ({rows.length})</option>
            <option value="extracto">Extracto — ingresos</option>
            <option value="ambas">Las dos hojas</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-stone-600">Período</span>
          <select name="periodo" defaultValue="todo"
                  className="rounded border border-stone-300 bg-white px-2 py-1.5">
            <option value="todo">Toda la historia</option>
            <option value="hoy">Hoy</option>
            <option value="7d">Últimos 7 días</option>
            <option value="mes">Este mes</option>
            <option value="rango">Rango de abajo</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-stone-600">Desde</span>
          <input type="date" name="desde"
                 className="rounded border border-stone-300 bg-white px-2 py-1.5" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-stone-600">Hasta</span>
          <input type="date" name="hasta"
                 className="rounded border border-stone-300 bg-white px-2 py-1.5" />
        </label>
        <button type="submit"
                className="rounded bg-stone-800 px-4 py-2 text-white hover:bg-stone-700">
          Descargar Excel
        </button>
        <span className="text-xs text-stone-500">
          🟢 90% · 🟡 50%, puede ser casualidad · 🔴 no encontrado
        </span>
      </form>

      {con90 === 0 && (
        <p className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
          <strong>Ninguno cruza por número de transacción + CUIT.</strong> Con estos dos
          archivos es lo esperado: son ejemplos sin relación entre sí. Los que aparecen
          al 50% coinciden en monto y fecha <em>por casualidad</em> — ninguno sobrevive
          si además se le exige el CUIT. Es justamente la prueba de por qué la regla del
          90% mira el CUIT antes que el importe.
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse bg-white text-sm">
          <thead>
            <tr className="border-b border-stone-300 text-left">
              <th className="px-3 py-2 font-medium">Comprobante</th>
              <th className="px-3 py-2 text-right font-medium">Monto</th>
              <th className="px-3 py-2 font-medium">Fecha</th>
              <th className="px-3 py-2 font-medium">Regla</th>
              <th className="px-3 py-2 font-medium">Hoja / fila del Excel</th>
              <th className="px-3 py-2 font-medium">Qué coincidió</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-stone-200 align-top">
                <td className="px-3 py-2">
                  <Link href={`/revisar/${r.id}`} className="text-sky-800 hover:underline">
                    {r.archivo}
                  </Link>
                  {r.revisado && <span className="ml-1 text-xs text-emerald-700">✓</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{plata(r.monto)}</td>
                <td className="px-3 py-2 tabular-nums">{r.fecha ?? '—'}</td>
                <td className="px-3 py-2">
                  {r.regla === '90' && (
                    <span className="rounded bg-emerald-100 px-2 py-0.5 text-emerald-900">
                      90%
                    </span>
                  )}
                  {r.regla === '50' && (
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">50%</span>
                  )}
                  {!r.regla && <span className="text-stone-500">no encontrado</span>}
                  {r.candidatos > 1 && (
                    <span className="block text-xs text-sky-800">
                      {r.candidatos} candidatos — ambiguo
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {r.hoja
                    ? <span className="tabular-nums">
                        <strong>{r.hoja}</strong> · fila {r.filaExcel}
                        <span className="block text-xs text-stone-500">
                          movimiento #{r.movId}
                        </span>
                      </span>
                    : <span className="text-stone-400">—</span>}
                </td>
                <td className="px-3 py-2 text-xs">
                  {r.movId ? (
                    <>
                      <div className="tabular-nums">
                        {r.movFecha} · {plata(r.movImporte)}
                      </div>
                      <div className="text-stone-600">
                        nro {r.movNro ?? '—'}
                        {r.movNro === r.referencia && r.movNro &&
                          <span className="text-emerald-700"> = referencia ✓</span>}
                      </div>
                      <div className="text-stone-600">
                        CUIT {r.movCuit ?? '—'}
                        {r.movCuit === r.cuitEmisor && r.movCuit &&
                          <span className="text-emerald-700"> = del comprobante ✓</span>}
                      </div>
                    </>
                  ) : (
                    <span className="text-stone-500">
                      buscalo a mano y decime con qué dato lo encontraste
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
