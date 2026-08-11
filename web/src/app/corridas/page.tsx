import { db } from '@/lib/db'
import { CAMPOS, type Campo, normalizarCampo } from '@/lib/importar-comprobantes'

export const dynamic = 'force-dynamic'

const ETIQUETAS: Record<Campo, string> = {
  tipo_operacion: 'tipo_operacion', monto: 'monto', moneda: 'moneda',
  fecha: 'fecha', hora: 'hora', nombre_emisor: 'nombre_emisor',
  cuit_emisor: 'cuit_emisor', cbu_cvu_emisor: 'cbu_cvu_emisor',
  banco_emisor: 'banco_emisor', nombre_receptor: 'nombre_receptor',
  cuit_receptor: 'cuit_receptor', cbu_cvu_receptor: 'cbu_cvu_receptor',
  banco_receptor: 'banco_receptor', concepto: 'concepto',
  referencia: 'referencia', coelsa_id: 'coelsa_id',
}

type Corrida = {
  nombre: string
  descripcion: string
  modelo: string
  prompt: string | null
  adaptador: string | null
  respectoDe: string | null
  queCambio: string | null
  creadoEn: string
  comprobantes: number
  conValor: number
}

type PorCampo = { corrida: string, campo: Campo, conValor: number }
type Revisado = { corrida: string, ia: Record<string, string | null>, verdad: Record<string, string | null> }

export default async function Corridas() {
  const { rows: corridas } = await db.query<Corrida>(
    `SELECT c.nombre, c.descripcion, c.modelo, c.prompt, c.adaptador,
            c.cambio_respecto_de AS "respectoDe", c.que_cambio AS "queCambio",
            to_char(c.creado_en,'YYYY-MM-DD HH24:MI') AS "creadoEn",
            count(e.id) AS comprobantes,
            coalesce(sum((SELECT count(*) FROM jsonb_each_text(e.campos) j
                          WHERE j.value IS NOT NULL AND j.value <> '')), 0) AS "conValor"
     FROM corrida c LEFT JOIN extraccion e ON e.corrida = c.nombre
     GROUP BY c.nombre, c.descripcion, c.modelo, c.prompt, c.adaptador,
              c.cambio_respecto_de, c.que_cambio, c.creado_en
     ORDER BY c.creado_en`)

  // Cuántos comprobantes tienen valor en cada campo, por corrida.
  const { rows: porCampo } = await db.query<PorCampo>(
    `SELECT e.corrida, j.key AS campo, count(*) AS "conValor"
     FROM extraccion e, jsonb_each_text(e.campos) j
     WHERE j.value IS NOT NULL AND j.value <> ''
     GROUP BY 1, 2`)

  // Aciertos contra la corrección humana: solo los comprobantes que una persona
  // ya revisó. Es la única medida que dice si el modelo ACIERTA — "tiene valor"
  // no es lo mismo que "tiene el valor correcto".
  //
  // La comparación se hace en TypeScript y no en SQL porque hay que normalizar
  // los dos lados con `normalizarCampo`: el modelo escribe `$ 81.687,80` y la
  // columna guarda `81687.80`. Comparándolos en crudo, el modelo "fallaba"
  // todos los montos, todas las fechas y todas las horas que había sacado bien.
  const { rows: revisados } = await db.query<Revisado>(
    `SELECT e.corrida, e.campos AS ia,
            jsonb_build_object(
              'tipo_operacion', c.tipo_operacion, 'monto', c.monto::text,
              'moneda', c.moneda, 'fecha', to_char(c.fecha,'YYYY-MM-DD'),
              'hora', to_char(c.hora,'HH24:MI'),
              'nombre_emisor', c.nombre_emisor, 'cuit_emisor', c.cuit_emisor,
              'cbu_cvu_emisor', c.cbu_cvu_emisor, 'banco_emisor', c.banco_emisor,
              'nombre_receptor', c.nombre_receptor, 'cuit_receptor', c.cuit_receptor,
              'cbu_cvu_receptor', c.cbu_cvu_receptor, 'banco_receptor', c.banco_receptor,
              'concepto', c.concepto, 'referencia', c.referencia, 'coelsa_id', c.coelsa_id
            ) AS verdad
     FROM comprobante c JOIN extraccion e ON e.comprobante_id = c.id
     WHERE c.revisado_en IS NOT NULL`)

  const valor = (corrida: string, campo: Campo) =>
    porCampo.find((p) => p.corrida === corrida && p.campo === campo)?.conValor ?? 0

  const acierto = (corrida: string, campo: Campo) => {
    const filas = revisados.filter((r) => r.corrida === corrida)
    if (filas.length === 0) return null
    const aciertos = filas.filter((r) =>
      normalizarCampo(campo, r.ia[campo]) === normalizarCampo(campo, r.verdad[campo])).length
    return { aciertos, revisados: filas.length }
  }
  const totalRevisados = new Set(revisados.map((r) => JSON.stringify(r.verdad))).size

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Comparación de corridas</h1>
        <p className="mt-2 max-w-3xl text-sm text-stone-600">
          Cada corrida es un modelo con un prompt y, si lo hay, un adaptador LoRA. Acá
          está qué cambió en cada una respecto de la anterior y qué efecto tuvo, campo
          por campo. Los números sin la explicación de qué se tocó no alcanzan para
          decidir el próximo paso.
        </p>
      </div>

      {totalRevisados === 0 && (
        <p className="rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>Todavía no hay comprobantes revisados por una persona.</strong> Sin eso
          solo se puede medir <em>cuántos campos llenó</em> el modelo, que no es lo mismo
          que <em>cuántos llenó bien</em>: un modelo que inventa valores llena todo y
          acierta poco. La columna de aciertos aparece cuando haya correcciones
          guardadas en <code className="rounded bg-amber-100 px-1">/revisar</code>.
        </p>
      )}

      <section className="space-y-4">
        {corridas.map((c) => {
          const total = Number(c.comprobantes) * CAMPOS.length
          const pct = total > 0 ? (100 * Number(c.conValor) / total) : 0
          return (
            <article key={c.nombre} className="rounded border border-stone-300 bg-white">
              <header className="flex flex-wrap items-baseline justify-between gap-3
                                 border-b border-stone-200 bg-stone-100 px-4 py-3">
                <h2 className="text-lg font-semibold">{c.nombre}</h2>
                <span className="text-sm tabular-nums text-stone-700">
                  {c.comprobantes} comprobantes · <strong>{c.conValor}</strong> campos con
                  valor de {total} ({pct.toFixed(1)}%)
                </span>
              </header>
              <div className="space-y-2 px-4 py-3 text-sm">
                <p>{c.descripcion}</p>
                <dl className="grid gap-x-6 gap-y-1 text-xs text-stone-600 sm:grid-cols-2">
                  <div><dt className="inline font-medium">modelo: </dt>
                    <dd className="inline font-mono">{c.modelo}</dd></div>
                  <div><dt className="inline font-medium">prompt: </dt>
                    <dd className="inline font-mono">{c.prompt ?? '—'}</dd></div>
                  <div><dt className="inline font-medium">adaptador LoRA: </dt>
                    <dd className="inline font-mono">{c.adaptador ?? 'ninguno (zero-shot)'}</dd></div>
                  <div><dt className="inline font-medium">cargada: </dt>
                    <dd className="inline tabular-nums">{c.creadoEn}</dd></div>
                </dl>
                {c.respectoDe && (
                  <div className="rounded border-l-4 border-sky-300 bg-sky-50 px-3 py-2">
                    <p className="text-xs font-medium text-sky-900">
                      Qué cambió respecto de {c.respectoDe}
                    </p>
                    <p className="mt-1 text-stone-800">{c.queCambio}</p>
                  </div>
                )}
              </div>
            </article>
          )
        })}
      </section>

      <section>
        <h2 className="mb-1 text-lg font-semibold">Campos con valor, por corrida</h2>
        <p className="mb-3 max-w-3xl text-sm text-stone-600">
          Cuántos comprobantes tienen algo en cada campo. La flecha compara contra la
          corrida de la que se derivó. <strong>Ojo:</strong> mide si el modelo llenó el
          campo, no si lo llenó bien.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse bg-white text-sm">
            <thead>
              <tr className="border-b border-stone-300">
                <th className="px-3 py-2 text-left font-medium">Campo</th>
                {corridas.map((c) => (
                  <th key={c.nombre} className="px-3 py-2 text-right font-medium">
                    {c.nombre}
                    <span className="block text-xs font-normal text-stone-500">
                      n={c.comprobantes}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CAMPOS.map((campo) => (
                <tr key={campo} className="border-b border-stone-200">
                  <td className="px-3 py-1.5 font-mono text-xs">{ETIQUETAS[campo]}</td>
                  {corridas.map((c) => {
                    const n = valor(c.nombre, campo)
                    const previa = c.respectoDe ? valor(c.respectoDe, campo) : null
                    const delta = previa === null ? null : n - previa
                    return (
                      <td key={c.nombre} className="px-3 py-1.5 text-right tabular-nums">
                        {n}
                        {delta !== null && delta !== 0 && (
                          <span className={delta > 0 ? 'text-emerald-700' : 'text-red-700'}>
                            {' '}{delta > 0 ? '▲' : '▼'}{Math.abs(delta)}
                          </span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {totalRevisados > 0 && (
        <section>
          <h2 className="mb-1 text-lg font-semibold">
            Aciertos contra la corrección humana
          </h2>
          <p className="mb-3 max-w-3xl text-sm text-stone-600">
            Sobre los comprobantes que una persona ya revisó. <strong>Esta es la medición
            que vale:</strong> compara lo que contestó el modelo contra lo que una persona
            confirmó mirando la imagen.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse bg-white text-sm">
              <thead>
                <tr className="border-b border-stone-300">
                  <th className="px-3 py-2 text-left font-medium">Campo</th>
                  {corridas.map((c) => (
                    <th key={c.nombre} className="px-3 py-2 text-right font-medium">
                      {c.nombre}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CAMPOS.map((campo) => (
                  <tr key={campo} className="border-b border-stone-200">
                    <td className="px-3 py-1.5 font-mono text-xs">{ETIQUETAS[campo]}</td>
                    {corridas.map((c) => {
                      const a = acierto(c.nombre, campo)
                      if (!a) return <td key={c.nombre} className="px-3 py-1.5 text-right text-stone-400">—</td>
                      const pct = 100 * Number(a.aciertos) / Number(a.revisados)
                      return (
                        <td key={c.nombre} className="px-3 py-1.5 text-right tabular-nums">
                          <span className={pct >= 80 ? 'text-emerald-800'
                            : pct >= 50 ? 'text-amber-800' : 'text-red-800'}>
                            {a.aciertos}/{a.revisados}
                          </span>
                          <span className="text-xs text-stone-500"> {pct.toFixed(0)}%</span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
