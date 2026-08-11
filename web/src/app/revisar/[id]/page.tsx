import Link from 'next/link'
import { notFound } from 'next/navigation'
import { db } from '@/lib/db'
import { CAMPOS, type Campo, normalizarCampo } from '@/lib/importar-comprobantes'
import { ETIQUETAS, motivosDeFormato } from '@/lib/revision'
import { Formulario } from './formulario'

export const dynamic = 'force-dynamic'

/** Los que la conciliación necesita. Se marcan para que salten a la vista. */
const CRITICOS = new Set<Campo>(['monto', 'fecha', 'cuit_emisor', 'referencia'])

const TIPO_INPUT: Partial<Record<Campo, string>> = { fecha: 'date', hora: 'time' }

type Fila = {
  id: number
  archivo: string
  corridaBase: string
  revisadoEn: string | null
  actual: Record<string, string | null>
  ia: Record<string, string | null>
  anterior: number | null
  siguiente: number | null
}

export default async function RevisarUno(props: PageProps<'/revisar/[id]'>) {
  const { id } = await props.params
  const { guardado, filtro } = await props.searchParams
  // El filtro viaja en la URL para que al guardar se siga por la misma cola: si
  // se está repasando "con dudas", el próximo tiene que ser otro con dudas.
  //
  // Sin filtro en la URL se asume "todos" y NO "pendientes": entrando por un
  // link pelado —el historial, la barra de direcciones, el "siguiente →"— con
  // los 51 ya revisados la cola de pendientes está vacía, no había próximo, y
  // guardar terminaba en la lista en vez del comprobante que sigue.
  const enFiltro = typeof filtro === 'string' ? filtro : 'todos'

  const { rows } = await db.query<Fila>(
    `SELECT c.id, c.archivo, c.corrida_base AS "corridaBase",
            to_char(c.revisado_en,'YYYY-MM-DD HH24:MI') AS "revisadoEn",
            -- los valores actuales (extracción o corrección) en la misma forma
            -- que los del modelo, para poder compararlos campo por campo
            jsonb_build_object(
              'tipo_operacion', c.tipo_operacion, 'monto', c.monto::text,
              'moneda', c.moneda, 'fecha', to_char(c.fecha,'YYYY-MM-DD'),
              'hora', to_char(c.hora,'HH24:MI'),
              'nombre_emisor', c.nombre_emisor, 'cuit_emisor', c.cuit_emisor,
              'cbu_cvu_emisor', c.cbu_cvu_emisor, 'banco_emisor', c.banco_emisor,
              'nombre_receptor', c.nombre_receptor, 'cuit_receptor', c.cuit_receptor,
              'cbu_cvu_receptor', c.cbu_cvu_receptor, 'banco_receptor', c.banco_receptor,
              'concepto', c.concepto, 'referencia', c.referencia, 'coelsa_id', c.coelsa_id
            ) AS actual,
            coalesce(e.campos, '{}'::jsonb) AS ia,
            (SELECT max(id) FROM comprobante WHERE id < c.id) AS anterior,
            (SELECT min(id) FROM comprobante WHERE id > c.id) AS siguiente
     FROM comprobante c
     LEFT JOIN extraccion e ON e.comprobante_id = c.id AND e.corrida = c.corrida_base
     WHERE c.id = $1`, [id])

  if (rows.length === 0) notFound()
  const c = rows[0]
  const limpio = (v: unknown) => (v === null || v === undefined ? '' : String(v).trim())
  // Normalizado de los dos lados: el modelo escribe `$ 81.687,80` y la columna
  // guarda `81687.80`. Comparar en crudo marcaba como "corregidos" campos que
  // el modelo había sacado bien.
  const difiere = (k: Campo) =>
    normalizarCampo(k, c.actual[k]) !== normalizarCampo(k, c.ia[k])
  const vacios = CAMPOS.filter((k) => !limpio(c.ia[k])).length
  const corregidos = CAMPOS.filter(difiere).length

  // Todo calculado acá: el formulario es cliente y no puede importar `lib/`,
  // que arrastra `pg`.
  const campos = CAMPOS.map((campo) => ({
    campo,
    etiqueta: ETIQUETAS[campo],
    critico: CRITICOS.has(campo),
    tipo: TIPO_INPUT[campo] ?? 'text',
    valor: limpio(c.actual[campo]),
    ia: limpio(c.ia[campo]),
    cambiado: difiere(campo),
  }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-xl font-semibold">
          <Link href={`/revisar?filtro=${enFiltro}`} className="text-sky-800 hover:underline">Revisar</Link>
          <span className="text-stone-400"> / </span>{c.archivo}
        </h1>
        <div className="flex gap-3 text-sm">
          {c.anterior && (
            <Link href={`/revisar/${c.anterior}?filtro=${enFiltro}`} className="text-sky-800 hover:underline">
              ← anterior
            </Link>
          )}
          {c.siguiente && (
            <Link href={`/revisar/${c.siguiente}?filtro=${enFiltro}`} className="text-sky-800 hover:underline">
              siguiente →
            </Link>
          )}
        </div>
      </div>

      {guardado && (
        <p className="rounded border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm
                      text-emerald-900">
          ✓ Comprobante {guardado} guardado. Este es el siguiente de la lista.
        </p>
      )}

      <p className="text-sm text-stone-600">
        Corrida <strong>{c.corridaBase}</strong> ·{' '}
        {c.revisadoEn
          ? <span className="text-emerald-800">
              revisado el {c.revisadoEn}, {corregidos} campos corregidos
            </span>
          : <>sin revisar · <strong>{vacios}</strong> de {CAMPOS.length} vacíos</>}
      </p>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-4 lg:self-start">
          <div className="rounded border border-stone-300 bg-white p-2">
            {/* `img` y no next/image: el archivo está fuera de public/ y lo sirve
                un route handler. El optimizador no aporta nada acá. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/api/comprobante/${c.id}/imagen`}
              alt={`Comprobante ${c.archivo}`}
              className="w-full rounded"
            />
          </div>
        </div>

        <Formulario id={c.id} campos={campos} filtro={enFiltro}
          motivos={motivosDeFormato(
            Object.fromEntries(CAMPOS.map((k) => [k, limpio(c.actual[k])])))} />
      </div>
    </div>
  )
}
