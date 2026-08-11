import Link from 'next/link'
import { db } from '@/lib/db'
import { cola, entra, type Filtro } from '@/lib/revision'
import { plata } from '../estados'

export const dynamic = 'force-dynamic'

type Fila = {
  id: number
  archivo: string
  corridaBase: string | null
  monto: string | null
  fecha: string | null
  bancoEmisor: string | null
  revisadoEn: string | null
  vacios: number
  corregidos: number
  cbuDudoso: boolean
}

const FILTROS: Record<Filtro, string> = {
  pendientes: 'Pendientes', revisados: 'Revisados', dudas: 'Con dudas', todos: 'Todos',
}

// Los sintéticos no se revisan: los fabricó `ia/generar.py` y su etiqueta sale
// de los mismos datos con que se dibujó la imagen. Corregirlos a mano es tiempo
// perdido, y además ensuciaría la medición: la verdad de referencia tiene que
// salir de comprobantes REALES o no mide nada del problema real.
//
// Ojo: que su etiqueta sea exacta depende de que el generador esté bien. Los 20
// que hay cargados hoy vienen de la versión que llenaba campos que la imagen no
// muestra, así que hay que recargarlos después de regenerar.
const SOLO_REALES = "c.corrida_base IS NOT NULL AND c.corrida_base <> 'sintetico'"

export default async function Revisar(props: PageProps<'/revisar'>) {
  const { filtro, guardado } = await props.searchParams

  // El chequeo de forma vive en `lib/revision.ts` y se calcula en TypeScript, así
  // que la cola se arma acá y no con un WHERE. Son 51 filas.
  const todos = await cola()
  const conteo = Object.fromEntries(
    (Object.keys(FILTROS) as Filtro[]).map((f) => [f, todos.filter((c) => entra(c, f)).length]),
  ) as Record<Filtro, number>

  // Al abrir sin filtro se muestran los pendientes, salvo que no quede ninguno:
  // recibir una pantalla vacía hace parecer que no hay nada cargado.
  const porDefecto: Filtro = conteo.pendientes > 0 ? 'pendientes' : 'todos'
  const activo: Filtro = (typeof filtro === 'string' && filtro in FILTROS)
    ? filtro as Filtro
    : porDefecto

  const motivosPorId = new Map(todos.map((c) => [c.id, c.motivos]))
  const enEsteFiltro = new Set(todos.filter((c) => entra(c, activo)).map((c) => c.id))

  const { rows: crudas } = await db.query<Fila>(
    `SELECT c.id, c.archivo, c.corrida_base AS "corridaBase", c.monto,
            to_char(c.fecha,'YYYY-MM-DD') AS fecha,
            c.banco_emisor AS "bancoEmisor",
            to_char(c.revisado_en,'YYYY-MM-DD HH24:MI') AS "revisadoEn",
            -- cuántos de los 16 dejó vacíos el modelo: dice dónde falla más
            (SELECT count(*) FROM jsonb_each_text(e.campos) j
             WHERE j.value IS NULL OR j.value = '') AS vacios,
            -- cuántos tuvo que corregir una persona. Solo tiene sentido si ya
            -- se revisó; antes de eso las columnas SON la extracción.
            CASE WHEN c.revisado_en IS NULL THEN 0 ELSE (
              SELECT count(*) FROM jsonb_each_text(e.campos) j
              WHERE j.value IS DISTINCT FROM (to_jsonb(c) ->> j.key)
            ) END AS corregidos,
            -- Transcripción dudosa: el comprobante dice a qué CBU fue la plata,
            -- pero ese CBU no está entre los propios aprobados en /cbu. Casi
            -- siempre es un dígito que la IA leyó mal, y no se nota mirando.
            (c.cbu_cvu_receptor IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM cbu_propio p WHERE p.cbu = c.cbu_cvu_receptor
             )) AS "cbuDudoso"
     FROM comprobante c
     LEFT JOIN extraccion e ON e.comprobante_id = c.id AND e.corrida = c.corrida_base
     WHERE ${SOLO_REALES}
     ORDER BY c.id`)

  const rows = crudas.filter((r) => enEsteFiltro.has(r.id))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Revisar extracción</h1>
        <p className="mt-2 max-w-3xl text-sm text-stone-600">
          Cada comprobante con lo que leyó la IA al lado de la imagen. Lo que corrijas
          es la verdad de referencia: sirve para medir cuánto acierta el modelo y para
          entrenarlo en la próxima tanda. Lo que contestó el modelo queda guardado
          aparte y no se pisa nunca — sin eso no habría contra qué comparar.
        </p>
      </div>

      {guardado && (
        <p className="rounded border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm
                      text-emerald-900">
          ✓ Comprobante {guardado} guardado. No queda ninguno más en esta lista.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {(Object.keys(FILTROS) as Filtro[]).map((f) => (
          <Link
            key={f}
            href={`/revisar?filtro=${f}`}
            className={`rounded border px-3 py-1.5 ${activo === f
              ? 'border-sky-700 bg-sky-800 font-medium text-white'
              : 'border-stone-300 bg-white text-stone-700 hover:bg-stone-100'}`}
          >
            {FILTROS[f]} ({conteo[f]})
          </Link>
        ))}
        {rows.length > 0 && (
          <Link href={`/revisar/${rows[0].id}?filtro=${activo}`}
                className="rounded bg-emerald-700 px-3 py-1.5 font-medium text-white
                           hover:bg-emerald-800">
            Revisar {rows.length} de corrido →
          </Link>
        )}
        <Link href="/corridas" className="ml-auto text-sky-800 hover:underline">
          Comparar corridas →
        </Link>
      </div>

      {activo === 'dudas' && (
        <p className="rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Comprobantes ya revisados donde un CUIT no da 11 dígitos, un CBU/CVU no da 22, o
          quedó guardado el texto <code>null</code> como si fuera un valor.{' '}
          <strong>No son errores confirmados:</strong> si la imagen mostraba el número
          cortado o enmascarado, lo que está guardado es correcto y no hay nada que tocar.
          Son los que conviene mirar de nuevo primero.
        </p>
      )}

      {rows.length === 0 && (
        <p className="py-8 text-stone-600">
          {conteo.todos === 0
            ? <>No hay comprobantes cargados. Se cargan con{' '}
                <code className="rounded bg-stone-200 px-1">pnpm importar:comprobantes</code>.</>
            : activo === 'pendientes'
              ? '🎉 No queda ninguno sin revisar.'
              : activo === 'dudas'
                ? '🎉 Ningún comprobante revisado tiene un CUIT ni un CBU de largo imposible.'
                : 'Todavía no revisaste ninguno.'}
        </p>
      )}

      {rows.length > 0 && (
        <table className="w-full border-collapse bg-white text-sm">
          <thead>
            <tr className="border-b border-stone-300 text-left">
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Archivo</th>
              <th className="px-3 py-2 font-medium">Corrida</th>
              <th className="px-3 py-2 font-medium">Banco</th>
              <th className="px-3 py-2 text-right font-medium">Monto</th>
              <th className="px-3 py-2 font-medium">Fecha</th>
              <th className="px-3 py-2 text-right font-medium">Vacíos</th>
              <th className="px-3 py-2 font-medium">Estado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-stone-200 hover:bg-stone-50">
                <td className="px-3 py-2 text-stone-500">{r.id}</td>
                <td className="px-3 py-2">
                  {/* El filtro viaja en la URL: al guardar, el "siguiente" sale
                      de esta misma cola y no de la de pendientes. */}
                  <Link href={`/revisar/${r.id}?filtro=${activo}`}
                        className="text-sky-800 hover:underline">
                    {r.archivo}
                  </Link>
                  {r.cbuDudoso && (
                    <span title="El CBU del receptor no está entre los propios aprobados"
                          className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">
                      CBU dudoso
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-stone-600">{r.corridaBase}</td>
                <td className="px-3 py-2">{r.bancoEmisor ?? '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums">{plata(r.monto)}</td>
                <td className="px-3 py-2 tabular-nums">{r.fecha ?? '—'}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {r.vacios > 0
                    ? <span className="text-amber-800">{r.vacios}</span>
                    : <span className="text-stone-400">0</span>}
                </td>
                <td className="px-3 py-2">
                  {r.revisadoEn
                    ? <span className="text-emerald-800">
                        revisado · {r.corregidos} corregidos
                      </span>
                    : <span className="text-stone-500">sin revisar</span>}
                  {(motivosPorId.get(r.id) ?? []).map((m) => (
                    <span key={m} className="block text-xs text-amber-800">{m}</span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
