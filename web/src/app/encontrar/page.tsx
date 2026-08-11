import Link from 'next/link'
import { db } from '@/lib/db'
import { candidatos, elegidas } from '@/lib/eleccion'
import { plata } from '../estados'

export const dynamic = 'force-dynamic'

/**
 * Dónde está parado el cruce comprobante ↔ extracto, de un vistazo.
 *
 * Esta pantalla NO resuelve: para eso está `/encontrar/[id]`, que muestra la
 * imagen al lado de las filas candidatas. Acá se ve el estado y se entra.
 *
 * Los contadores son el punto de todo esto mientras la regla se desarrolla:
 * dicen cuántos resuelve el algoritmo solo y cuántos hay que corregir a mano.
 * Si la segunda cifra no baja, la regla todavía no sirve.
 *
 * La cascada vive en `lib/eleccion.ts` y no acá: la usa también la pantalla de
 * a uno, y tenerla escrita dos veces garantizaba que un día dijeran distinto.
 */

type Fila = {
  id: number
  archivo: string
  monto: string | null
  fecha: string | null
  revisado: boolean
}

export default async function Encontrar({ searchParams }: PageProps<'/encontrar'>) {
  const { error } = await searchParams

  const { rows: filas } = await db.query<Fila>(
    `SELECT id, archivo, monto, to_char(fecha,'YYYY-MM-DD') AS fecha,
            revisado_en IS NOT NULL AS revisado
     FROM comprobante
     -- Los sintéticos tienen montos inventados por un script: nunca van a
     -- cruzar con un extracto real y solo inflarían el "no encontrado".
     WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico'
     ORDER BY id`)

  const propuestas = await candidatos()
  const elecciones = await elegidas()

  const porComprobante = new Map<number, typeof propuestas>()
  for (const p of propuestas) {
    const l = porComprobante.get(p.comprobanteId) ?? []
    l.push(p)
    porComprobante.set(p.comprobanteId, l)
  }

  /** `elegido` gana sobre todo: una persona ya lo miró y no se vuelve a preguntar. */
  const situacion = (f: Fila) => {
    if (elecciones.has(f.id)) return 'elegido'
    const n = porComprobante.get(f.id)?.length ?? 0
    return n === 0 ? 'sin_candidatos' : n === 1 ? 'unico' : 'ambiguo'
  }

  const cuenta = (s: string) => filas.filter((f) => situacion(f) === s).length
  // De lo elegido a mano: cuántas veces se corrigió al algoritmo (eligió otra
  // fila de la que él proponía). Es la medida de si la regla sirve.
  const corregidos = filas.filter((f) => {
    const e = elecciones.get(f.id)
    const p = porComprobante.get(f.id) ?? []
    return e !== undefined && p.length === 1 && p[0].id !== e
  }).length

  // Primero lo que pide atención. Dentro de cada grupo por id, que no se mueve.
  const orden = { sin_candidatos: 0, ambiguo: 1, elegido: 2, unico: 3 } as const
  const ordenadas = [...filas].sort((a, b) =>
    orden[situacion(a) as keyof typeof orden] - orden[situacion(b) as keyof typeof orden]
    || a.id - b.id)

  const pendientes = cuenta('sin_candidatos') + cuenta('ambiguo')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Comprobante ↔ extracto</h1>
        <p className="mt-2 max-w-3xl text-sm text-stone-600">
          Qué fila del extracto le corresponde a cada comprobante. Entrá a uno para ver la
          imagen al lado de las filas candidatas, y elegir o buscar la correcta.
        </p>
      </div>

      {error && (
        <p className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
          {Array.isArray(error) ? error[0] : error}
        </p>
      )}

      <div className="flex flex-wrap gap-3 text-sm">
        <span className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5">
          <strong>{cuenta('unico')}</strong> los resolvió la regla
        </span>
        <span className="rounded border border-sky-300 bg-sky-50 px-3 py-1.5">
          <strong>{cuenta('elegido')}</strong> los elegiste vos
          {corregidos > 0 && <span className="ml-1 text-xs">({corregidos} corrigiendo)</span>}
        </span>
        <span className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5">
          <strong>{cuenta('ambiguo')}</strong> con varios candidatos
        </span>
        <span className="rounded border border-stone-300 bg-white px-3 py-1.5">
          <strong>{cuenta('sin_candidatos')}</strong> sin encontrar
        </span>
        <span className="rounded border border-stone-200 bg-stone-50 px-3 py-1.5 text-stone-600">
          {filas.length} comprobantes reales
        </span>
      </div>

      {pendientes > 0 && ordenadas[0] && (
        <Link href={`/encontrar/${ordenadas[0].id}`}
              className="inline-block rounded bg-stone-800 px-4 py-2 text-sm text-white hover:bg-stone-700">
          Resolver los {pendientes} pendientes →
        </Link>
      )}

      {/* El export es un GET a mano y no una Server Action: lo que devuelve es
          un archivo para descargar, no una navegación. El navegador ya sabe
          hacer esto con un <form method="get">, sin una línea de JavaScript. */}
      <form action="/api/exportar" method="get"
            className="flex flex-wrap items-end gap-3 rounded border border-stone-300 bg-stone-50 px-4 py-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-stone-600">Qué exportar</span>
          <select name="que" defaultValue="comprobantes"
                  className="rounded border border-stone-300 bg-white px-2 py-1.5">
            <option value="comprobantes">Comprobantes ({filas.length})</option>
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
      </form>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse bg-white text-sm">
          <thead>
            <tr className="border-b border-stone-300 text-left">
              <th className="px-3 py-2 font-medium">Comprobante</th>
              <th className="px-3 py-2 text-right font-medium">Monto</th>
              <th className="px-3 py-2 font-medium">Fecha</th>
              <th className="px-3 py-2 font-medium">Situación</th>
              <th className="px-3 py-2 font-medium">Fila del extracto</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {ordenadas.map((f) => {
              const s = situacion(f)
              const props = porComprobante.get(f.id) ?? []
              const elegida = props.find((p) => p.id === elecciones.get(f.id))
              const mostrar = s === 'elegido' ? elegida : s === 'unico' ? props[0] : undefined
              return (
                <tr key={f.id} className="border-b border-stone-200">
                  <td className="px-3 py-2">
                    <Link href={`/encontrar/${f.id}`} className="text-sky-800 hover:underline">
                      {f.archivo}
                    </Link>
                    {f.revisado && <span className="ml-1 text-xs text-emerald-700">✓</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{plata(f.monto)}</td>
                  <td className="px-3 py-2 tabular-nums">{f.fecha ?? '—'}</td>
                  <td className="px-3 py-2">
                    {s === 'unico' && (
                      <span className="rounded bg-emerald-100 px-2 py-0.5 text-emerald-900">
                        {props[0].regla}% · la regla
                      </span>
                    )}
                    {s === 'elegido' && (
                      <span className="rounded bg-sky-100 px-2 py-0.5 text-sky-900">
                        lo elegiste vos
                      </span>
                    )}
                    {s === 'ambiguo' && (
                      <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">
                        {props.length} candidatos
                      </span>
                    )}
                    {s === 'sin_candidatos' && (
                      <span className="text-stone-500">sin encontrar</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs tabular-nums">
                    {mostrar
                      ? <>
                          <strong>{mostrar.hoja}</strong> · fila {mostrar.fila}
                          <span className="block text-stone-500">
                            {mostrar.fecha} · {plata(mostrar.importe)}
                          </span>
                        </>
                      : <span className="text-stone-400">—</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/encontrar/${f.id}`}
                          className="text-xs text-sky-800 underline hover:text-sky-950">
                      {s === 'unico' || s === 'elegido' ? 'ver' : 'resolver'}
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
