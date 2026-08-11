import Link from 'next/link'
import { tablero, sinComprobante } from '@/lib/conciliacion'
import { db } from '@/lib/db'
import { recalcular } from './acciones'
import { ESTADOS, Etiqueta, plata, type ClaveEstado } from './estados'

// Lee de Postgres en cada request: nada de esto se puede cachear.
export const dynamic = 'force-dynamic'

type Movimiento = {
  id: number; cuenta: string; fecha: string; importe: string; descripcion: string
}

export default async function Tablero(
  { searchParams }: { searchParams: Promise<{ estado?: string; cuenta?: string }> },
) {
  // En Next 16 `searchParams` es una Promise: hay que esperarla.
  const { estado, cuenta } = await searchParams
  const { rows: cuentas } = await db.query<{ nombre: string }>(
    'SELECT nombre FROM cuenta WHERE activa ORDER BY nombre')

  // "Sin comprobante" es el único estado que no vive en `conciliacion`: es un
  // movimiento que nadie reclamó, así que se lista aparte.
  const esSinComprobante = estado === 'sin_comprobante'
  const filas = esSinComprobante ? [] : await tablero({ estado, cuenta })
  const huerfanos = esSinComprobante
    ? (await sinComprobante(cuenta)) as Movimiento[]
    : []

  const { rows: conteos } = await db.query<{ estado: string; n: number }>(
    'SELECT estado, count(*)::int AS n FROM conciliacion GROUP BY estado')
  const { rows: [{ huerfanosTotal }] } = await db.query<{ huerfanosTotal: number }>(
    `SELECT count(*)::int AS "huerfanosTotal" FROM movimiento m WHERE m.es_ingreso
       AND NOT EXISTS (SELECT 1 FROM conciliacion c
         WHERE c.movimiento_id = m.id OR c.movimiento_pretendido = m.id
            OR m.id = ANY(c.candidatos))`)

  const total = (clave: string) =>
    clave === 'sin_comprobante'
      ? huerfanosTotal
      : conteos.find((c) => c.estado === clave)?.n ?? 0

  const link = (cambios: Record<string, string | undefined>) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries({ estado, cuenta, ...cambios })) if (v) q.set(k, v)
    return `/?${q}`
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold">Tablero</h1>
        <form action={recalcular}>
          <button className="rounded border border-stone-400 bg-white px-3 py-1.5 text-sm hover:bg-stone-100">
            Recalcular
          </button>
        </form>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {(Object.keys(ESTADOS) as ClaveEstado[]).map((clave) => (
          <Link
            key={clave}
            href={link({ estado: estado === clave ? undefined : clave })}
            className={`rounded border p-3 ${ESTADOS[clave].color} ${
              estado === clave ? 'ring-2 ring-stone-800' : ''
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium">{ESTADOS[clave].etiqueta}</span>
              <span className="text-xl font-semibold tabular-nums">{total(clave)}</span>
            </div>
            <p className="mt-1 text-xs leading-snug opacity-80">{ESTADOS[clave].que}</p>
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-stone-600">Cuenta:</span>
        <Link
          href={link({ cuenta: undefined })}
          className={`rounded border px-2 py-1 ${!cuenta ? 'bg-stone-800 text-white' : 'bg-white'}`}
        >
          Todas
        </Link>
        {cuentas.map((c) => (
          <Link
            key={c.nombre}
            href={link({ cuenta: c.nombre })}
            className={`rounded border px-2 py-1 ${
              cuenta === c.nombre ? 'bg-stone-800 text-white' : 'bg-white'
            }`}
          >
            {c.nombre}
          </Link>
        ))}
        {(estado || cuenta) && (
          <Link href="/" className="ml-2 text-stone-600 underline">limpiar filtros</Link>
        )}
      </div>

      {esSinComprobante ? (
        <Tabla
          columnas={['Movimiento', 'Cuenta', 'Fecha', 'Importe', 'Descripción']}
          filas={huerfanos.map((m) => [
            `#${m.id}`, m.cuenta, m.fecha, plata(m.importe), m.descripcion,
          ])}
          vacio="No hay ingresos sin comprobante."
        />
      ) : (
        <Tabla
          columnas={['Comprobante', 'Estado', 'Cuenta', 'Fecha', 'Monto', 'Movimiento', 'Decidido por']}
          filas={filas.map((f) => [
            `#${f.comprobanteId}`,
            <Etiqueta key="e" estado={f.estado} />,
            f.cuenta ?? <span key="d" className="text-stone-500">cuenta desconocida</span>,
            f.fecha ?? '—',
            plata(f.monto),
            f.estado === 'ambiguo'
              ? <Link key="r" href="/resolver" className="underline">
                  {f.candidatos.length} candidatos
                </Link>
              : f.movimientoId ? `#${f.movimientoId}` : '—',
            f.decididoPor,
          ])}
          vacio="No hay comprobantes con ese filtro. Cargá uno para empezar."
        />
      )}
    </div>
  )
}

function Tabla(
  { columnas, filas, vacio }:
  { columnas: string[]; filas: React.ReactNode[][]; vacio: string },
) {
  if (filas.length === 0) return <p className="py-8 text-stone-600">{vacio}</p>
  return (
    <div className="overflow-x-auto rounded border border-stone-300 bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-stone-300 bg-stone-100 text-left">
          <tr>{columnas.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}</tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={i} className="border-b border-stone-200 last:border-0">
              {fila.map((celda, j) => (
                <td key={j} className="px-3 py-2 align-top">{celda}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
