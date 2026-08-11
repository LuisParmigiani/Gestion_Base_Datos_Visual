import { db } from '@/lib/db'
import { elegirCandidato } from '../acciones'
import { plata } from '../estados'

export const dynamic = 'force-dynamic'

type Ambiguo = {
  comprobanteId: number
  archivo: string
  monto: string | null
  fecha: string | null
  cuitEmisor: string | null
  candidatos: number[]
}

type Candidato = {
  id: number
  fecha: string
  importe: string | null
  descripcion: string
  cuitEmisor: string | null
  cuenta: string
}

export default async function Resolver() {
  const { rows: ambiguos } = await db.query<Ambiguo>(
    `SELECT co.id AS "comprobanteId", co.archivo, co.monto,
            to_char(co.fecha, 'YYYY-MM-DD') AS fecha,
            co.cuit_emisor AS "cuitEmisor", cc.candidatos
     FROM conciliacion cc JOIN comprobante co ON co.id = cc.comprobante_id
     WHERE cc.estado = 'ambiguo' ORDER BY co.fecha, co.id`)

  const ids = [...new Set(ambiguos.flatMap((a) => a.candidatos))]
  const { rows: candidatos } = ids.length === 0
    ? { rows: [] as Candidato[] }
    : await db.query<Candidato>(
      `SELECT m.id, to_char(m.fecha, 'YYYY-MM-DD') AS fecha, m.importe, m.descripcion,
              m.cuit_emisor AS "cuitEmisor", c.nombre AS cuenta
       FROM movimiento m JOIN cuenta c ON c.id = m.cuenta_id WHERE m.id = ANY($1)`, [ids])

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Resolver ambiguos</h1>
        <p className="mt-2 text-sm text-stone-600">
          Varios movimientos coinciden en importe y fecha con el mismo comprobante. La
          máquina no elige: cuál corresponde lo decide una persona. Lo que se elija acá
          queda marcado como decisión humana y ningún recálculo lo pisa.
        </p>
      </div>

      {ambiguos.length === 0 && (
        <p className="py-8 text-stone-600">No hay nada ambiguo para resolver.</p>
      )}

      {ambiguos.map((a) => (
        <section key={a.comprobanteId} className="rounded border border-sky-300 bg-white">
          <header className="border-b border-stone-200 bg-sky-50 px-5 py-3">
            <h2 className="font-medium">Comprobante #{a.comprobanteId}</h2>
            <p className="mt-1 text-sm text-stone-700">
              {plata(a.monto)} · {a.fecha ?? 'sin fecha'}
              {a.cuitEmisor && <> · CUIT {a.cuitEmisor}</>} · <span className="text-stone-500">{a.archivo}</span>
            </p>
          </header>
          <ul className="divide-y divide-stone-200">
            {a.candidatos.map((id) => {
              const m = candidatos.find((c) => c.id === id)
              if (!m) return null
              return (
                <li key={id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                  <div className="text-sm">
                    <p className="font-medium">
                      Movimiento #{m.id} · {plata(m.importe)} · {m.fecha}
                    </p>
                    <p className="text-stone-600">
                      {m.cuenta} · {m.descripcion}
                      {m.cuitEmisor && <> · CUIT {m.cuitEmisor}</>}
                    </p>
                  </div>
                  <form action={elegirCandidato}>
                    <input type="hidden" name="comprobante" value={a.comprobanteId} />
                    <input type="hidden" name="movimiento" value={m.id} />
                    <button className="rounded border border-stone-400 bg-white px-3 py-1.5 text-sm hover:bg-stone-100">
                      Es este
                    </button>
                  </form>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}
