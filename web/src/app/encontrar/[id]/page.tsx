import Link from 'next/link'
import { notFound } from 'next/navigation'
import { db } from '@/lib/db'
import {
  candidatos, buscarMovimientos, elegidas,
  type MovimientoEncontrado, type CandidatoFila,
} from '@/lib/eleccion'
import { plata } from '../../estados'
import { elegirMovimiento, quitarEleccion } from '../../acciones'

export const dynamic = 'force-dynamic'

/**
 * Asignarle a UN comprobante su fila del extracto: la imagen a la izquierda y
 * las filas candidatas a la derecha, igual que /revisar.
 *
 * Por qué de a uno y no todo en la lista: para decidir entre dos movimientos del
 * mismo importe hay que MIRAR el comprobante. La lista sirve para ver dónde está
 * parado el algoritmo; esto sirve para resolver.
 *
 * Cuando la cascada no propone nada, en vez de una pantalla vacía aparecen los
 * movimientos más cercanos en fecha, y un buscador por detalle, monto y fecha.
 * Es un punto de partida, no una respuesta: ninguna de esas filas está elegida
 * hasta que alguien apriete el botón.
 */

type Comprobante = {
  id: number
  archivo: string
  monto: string | null
  fecha: string | null
  hora: string | null
  nombreEmisor: string | null
  cuitEmisor: string | null
  bancoEmisor: string | null
  nombreReceptor: string | null
  concepto: string | null
  referencia: string | null
  coelsaId: string | null
  revisado: boolean
}

export default async function AsignarUno(
  { params, searchParams }: PageProps<'/encontrar/[id]'>,
) {
  const { id } = await params
  const { detalle, monto, fecha, error } = await searchParams
  const uno = (v: string | string[] | undefined) => Array.isArray(v) ? v[0] : v

  const { rows: [c] } = await db.query<Comprobante>(
    `SELECT id, archivo, monto, to_char(fecha,'YYYY-MM-DD') AS fecha,
            to_char(hora,'HH24:MI') AS hora,
            nombre_emisor AS "nombreEmisor", cuit_emisor AS "cuitEmisor",
            banco_emisor AS "bancoEmisor", nombre_receptor AS "nombreReceptor",
            concepto, referencia, coelsa_id AS "coelsaId",
            revisado_en IS NOT NULL AS revisado
     FROM comprobante WHERE id = $1`, [Number(id)])
  if (!c) notFound()

  const propuestos = await candidatos(c.id)
  const elegido = (await elegidas()).get(c.id) ?? null

  // Solo se busca si la cascada no resolvió, o si la persona escribió algo. Con
  // un candidato único y sin búsqueda, la pantalla no tiene por qué ofrecer 50
  // filas más: sería empujar a dudar de algo que ya está bien.
  const buscando = Boolean(uno(detalle) || uno(monto) || uno(fecha))
  const hayQueBuscar = buscando || (propuestos.length === 0 && elegido === null)
  const resultado = hayQueBuscar
    ? await buscarMovimientos({
      detalle: uno(detalle), monto: uno(monto), fecha: uno(fecha),
      // Sin filtros, lo más cercano a la fecha del comprobante primero.
      cerca: buscando ? undefined : (c.fecha ?? undefined),
    })
    : { filas: [] as MovimientoEncontrado[], total: 0 }

  // La cola para moverse: los mismos comprobantes que lista /encontrar, por id,
  // que es lo único que no se mueve cuando se guarda algo.
  const { rows: cola } = await db.query<{ id: number }>(
    `SELECT id FROM comprobante
     WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico' ORDER BY id`)
  const i = cola.findIndex((f) => f.id === c.id)
  const anterior = i > 0 ? cola[i - 1].id : null
  const siguiente = i >= 0 && i < cola.length - 1 ? cola[i + 1].id : null

  // La fila elegida puede NO estar entre las que propone la regla: es
  // justamente lo que pasa cuando se la buscó a mano. Si no está, se la relee
  // por id — si no, la pantalla se olvidaría de lo que la persona ya decidió.
  const yaElegido = elegido === null ? undefined
    : propuestos.find((p) => p.id === elegido)
      ?? (await buscarMovimientos({ id: elegido })).filas[0]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">
          {c.archivo}
          {c.revisado && <span className="ml-2 text-sm text-emerald-700">✓ revisado</span>}
        </h1>
        <div className="flex items-center gap-3 text-sm">
          <Link href="/encontrar" className="text-sky-800 hover:underline">← la lista</Link>
          {anterior && (
            <Link href={`/encontrar/${anterior}`} className="text-sky-800 hover:underline">
              anterior
            </Link>
          )}
          {siguiente && (
            <Link href={`/encontrar/${siguiente}`}
                  className="rounded bg-stone-800 px-3 py-1.5 text-white hover:bg-stone-700">
              siguiente →
            </Link>
          )}
        </div>
      </div>

      {error && (
        <p className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
          {uno(error)}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3 lg:sticky lg:top-4 lg:self-start">
          <div className="rounded border border-stone-300 bg-white p-2">
            {/* `img` y no next/image: el archivo está fuera de public/ y lo sirve
                un route handler. El optimizador no aporta nada acá. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/comprobante/${c.id}/imagen`} alt={`Comprobante ${c.archivo}`}
                 className="w-full rounded" />
          </div>

          {/* Los datos que sirven para reconocer la fila, juntos y grandes. */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border border-stone-300
                         bg-white p-4 text-sm">
            <Dato k="Monto" v={plata(c.monto)} fuerte />
            <Dato k="Fecha" v={`${c.fecha ?? '—'}${c.hora ? ` · ${c.hora}` : ''}`} fuerte />
            <Dato k="Nro / referencia" v={c.referencia} />
            <Dato k="CUIT del emisor" v={c.cuitEmisor} />
            <Dato k="Emisor" v={c.nombreEmisor} />
            <Dato k="Banco" v={c.bancoEmisor} />
            <Dato k="Receptor" v={c.nombreReceptor} />
            <Dato k="Concepto" v={c.concepto} />
            <Dato k="ID COELSA" v={c.coelsaId} />
          </dl>
        </div>

        <div className="space-y-4">
          {yaElegido && (
            <section className="rounded border border-sky-300 bg-sky-50 p-4">
              <h2 className="text-sm font-semibold text-sky-900">Elegiste esta fila</h2>
              <div className="mt-2"><Fila m={yaElegido} c={c} /></div>
              <form action={quitarEleccion} className="mt-2">
                <input type="hidden" name="comprobante" value={c.id} />
                <input type="hidden" name="volverA" value={`/encontrar/${c.id}`} />
                <button className="text-xs text-stone-600 underline hover:text-stone-900">
                  deshacer y volver a elegir
                </button>
              </form>
            </section>
          )}

          {!yaElegido && propuestos.length > 0 && (
            <section className="rounded border border-stone-300 bg-white p-4">
              <h2 className="text-sm font-semibold">
                {propuestos.length === 1
                  ? 'La regla propone esta fila'
                  : `La regla encontró ${propuestos.length} filas posibles — elegí una`}
              </h2>
              <ul className="mt-3 space-y-3">
                {propuestos.map((m) => (
                  <li key={m.id} className="rounded border border-stone-200 bg-stone-50 p-3">
                    <Fila m={m} c={c} />
                    <Elegir comprobante={c.id} movimiento={m.id} tomadoPor={m.tomadoPor} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {!yaElegido && propuestos.length === 0 && (
            <p className="rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <strong>La regla no encontró ninguna fila.</strong> Abajo están los movimientos
              más cercanos a la fecha del comprobante, y podés buscar por detalle, monto o fecha.
            </p>
          )}

          {hayQueBuscar && (
            <section className="rounded border border-stone-300 bg-white p-4">
              <h2 className="text-sm font-semibold">Buscar en el extracto</h2>
              {/* GET y sin JavaScript: el navegador ya sabe mandar un formulario
                  y la búsqueda queda en la URL, así que se puede compartir. */}
              <form method="get" className="mt-3 flex flex-wrap items-end gap-2 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-stone-600">Detalle</span>
                  <input name="detalle" defaultValue={uno(detalle) ?? ''}
                         placeholder="texto de la descripción"
                         className="w-56 rounded border border-stone-400 px-2 py-1.5" />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-stone-600">Monto</span>
                  <input name="monto" defaultValue={uno(monto) ?? ''} placeholder="4800.50"
                         className="w-32 rounded border border-stone-400 px-2 py-1.5" />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-stone-600">Fecha</span>
                  <input type="date" name="fecha" defaultValue={uno(fecha) ?? ''}
                         className="rounded border border-stone-400 px-2 py-1.5" />
                </label>
                <button className="rounded bg-stone-800 px-3 py-2 text-white hover:bg-stone-700">
                  Buscar
                </button>
                {buscando && (
                  <Link href={`/encontrar/${c.id}`}
                        className="px-2 py-2 text-stone-600 underline hover:text-stone-900">
                    limpiar
                  </Link>
                )}
              </form>

              <p className="mt-3 text-xs text-stone-600">
                {resultado.total === 0
                  ? 'Ninguna fila coincide.'
                  : `${resultado.total} fila(s)${
                    resultado.total > resultado.filas.length
                      ? ` — se muestran las primeras ${resultado.filas.length}`
                      : ''}`}
              </p>

              <ul className="mt-2 space-y-3">
                {resultado.filas.map((m) => (
                  <li key={m.id} className="rounded border border-stone-200 bg-stone-50 p-3">
                    <Fila m={m} c={c} />
                    <Elegir comprobante={c.id} movimiento={m.id} tomadoPor={m.tomadoPor} />
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

function Dato({ k, v, fuerte }: { k: string, v: string | null, fuerte?: boolean }) {
  return (
    <>
      <dt className="text-stone-600">{k}</dt>
      <dd className={`tabular-nums ${fuerte ? 'font-semibold' : ''}`}>{v || '—'}</dd>
    </>
  )
}

/**
 * Una fila del extracto. Lo que coincide con el comprobante va en verde: es lo
 * único que separa "esta es" de "esta se parece".
 */
function Fila(
  { m, c }: { m: MovimientoEncontrado | CandidatoFila, c: Comprobante },
) {
  const regla = 'regla' in m ? m.regla : null
  const dias = 'dias' in m ? m.dias : null
  const mismoMonto = m.importe !== null && c.monto !== null && Number(m.importe) === Number(c.monto)
  return (
    <div className="text-sm">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold tabular-nums">
          {m.hoja} · fila {m.fila}
        </span>
        {regla && (
          <span className={`rounded px-2 py-0.5 text-xs ${
            regla === '90' ? 'bg-emerald-100 text-emerald-900' : 'bg-amber-100 text-amber-900'}`}>
            {regla}%
          </span>
        )}
        {dias !== null && dias !== 0 && (
          <span className="text-xs text-amber-800">
            {dias > 0 ? '+' : ''}{dias} días
          </span>
        )}
      </div>
      <div className="tabular-nums">
        {m.fecha} · <span className={mismoMonto ? 'font-semibold text-emerald-800' : ''}>
          {plata(m.importe)}
        </span>
      </div>
      <div className="text-xs text-stone-600">{m.descripcion}</div>
      <div className="text-xs text-stone-600">
        nro {m.nroTransaccion ?? '—'}
        {m.nroTransaccion && m.nroTransaccion === c.referencia && (
          <span className="text-emerald-700"> = referencia ✓</span>
        )}
        {' · '}CUIT {m.cuitEmisor ?? '—'}
        {m.cuitEmisor && m.cuitEmisor === c.cuitEmisor && (
          <span className="text-emerald-700"> = del comprobante ✓</span>
        )}
      </div>
    </div>
  )
}

function Elegir(
  { comprobante, movimiento, tomadoPor }:
  { comprobante: number, movimiento: number, tomadoPor: string | null },
) {
  if (tomadoPor) {
    return (
      <p className="mt-2 text-xs text-stone-500">
        ya asignada a {tomadoPor}
      </p>
    )
  }
  return (
    <form action={elegirMovimiento} className="mt-2">
      <input type="hidden" name="comprobante" value={comprobante} />
      <input type="hidden" name="movimiento" value={movimiento} />
      <input type="hidden" name="volverA" value={`/encontrar/${comprobante}`} />
      <button className="rounded border border-sky-700 px-3 py-1 text-xs text-sky-800 hover:bg-sky-100">
        Es esta
      </button>
    </form>
  )
}
