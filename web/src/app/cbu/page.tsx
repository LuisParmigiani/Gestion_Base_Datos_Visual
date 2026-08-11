import Link from 'next/link'
import { db } from '@/lib/db'
import { agregarCbu, borrarCbu } from '../acciones'

export const dynamic = 'force-dynamic'

/**
 * Los CBU/CVU propios: los que la plata entra de verdad.
 *
 * La regla, en palabras del usuario: "nuestro CBU no cambia. Puede que haya
 * alguno nuevo, pero no va a ser lo más normal, por lo que ponelo como dudosa
 * y última a revisión manual".
 *
 * Medido sobre los 51 comprobantes corregidos a mano: 43 traen CBU de receptor
 * y hay **6 valores distintos**. Un CBU que no esté en la lista aprobada es,
 * casi siempre, un dígito que la IA leyó mal — y eso no se nota mirando.
 *
 * Los candidatos NO se aprueban solos. Que un número aparezca 20 veces no lo
 * hace correcto: si el modelo leyó mal el mismo dígito en 20 comprobantes del
 * mismo banco, aprobarlo automáticamente convertiría el error en la regla.
 */
export default async function Cbu(props: PageProps<'/cbu'>) {
  const { ok, error } = await props.searchParams

  const { rows: propios } = await db.query<{
    id: number; cbu: string; nota: string | null; cuenta: string | null; usados: number
  }>(
    `SELECT p.id, p.cbu, p.nota, c.nombre AS cuenta,
            (SELECT count(*) FROM comprobante k
             WHERE k.cbu_cvu_receptor = p.cbu)::int AS usados
     FROM cbu_propio p LEFT JOIN cuenta c ON c.id = p.cuenta_id
     ORDER BY usados DESC, p.id`)

  // Los CBU de receptor que aparecen en comprobantes REVISADOS y todavía no
  // están aprobados. Se ofrecen para aprobar de a uno.
  const { rows: candidatos } = await db.query<{ cbu: string; veces: number }>(
    `SELECT cbu_cvu_receptor AS cbu, count(*)::int AS veces
     FROM comprobante
     WHERE cbu_cvu_receptor IS NOT NULL AND revisado_en IS NOT NULL
       AND corrida_base <> 'sintetico'
       AND NOT EXISTS (SELECT 1 FROM cbu_propio p WHERE p.cbu = cbu_cvu_receptor)
     GROUP BY 1 ORDER BY 2 DESC`)

  const { rows: [dudosos] } = await db.query<{ dudosos: number; total: number }>(
    `SELECT count(*) FILTER (
       WHERE cbu_cvu_receptor IS NOT NULL
         AND NOT EXISTS (SELECT 1 FROM cbu_propio p WHERE p.cbu = cbu_cvu_receptor)
     )::int AS dudosos,
     count(*)::int AS total
     FROM comprobante WHERE corrida_base <> 'sintetico'`)

  const { rows: cuentas } = await db.query<{ id: number; nombre: string }>(
    'SELECT id, nombre FROM cuenta ORDER BY nombre')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">CBU y CVU propios</h1>
        <p className="mt-2 max-w-3xl text-sm text-stone-600">
          Las cuentas donde entra la plata. Un comprobante cuyo CBU de receptor no
          esté en esta lista queda como <strong>transcripción dudosa</strong> y va a
          revisión manual, porque lo más probable es que la IA haya leído mal un
          dígito — y un dígito cambiado en un CBU no se ve.
        </p>
      </div>

      {ok && (
        <p className="rounded border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm text-emerald-900">
          Guardado. Los comprobantes que usaban ese CBU dejaron de ser dudosos.
        </p>
      )}
      {typeof error === 'string' && (
        <p className="rounded border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-900">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-3 text-sm">
        <span className="rounded border border-emerald-300 bg-emerald-50 px-3 py-1.5">
          <strong>{propios.length}</strong> CBU aprobados
        </span>
        <span className={`rounded border px-3 py-1.5 ${dudosos.dudosos > 0
          ? 'border-amber-300 bg-amber-50' : 'border-stone-300 bg-white'}`}>
          <strong>{dudosos.dudosos}</strong> comprobantes con transcripción dudosa
          <span className="text-stone-500"> de {dudosos.total}</span>
        </span>
      </div>

      {candidatos.length > 0 && (
        <section className="rounded border border-amber-300 bg-amber-50 p-4">
          <h2 className="font-medium">Candidatos — aparecen en tus comprobantes revisados</h2>
          <p className="mt-1 text-sm text-stone-700">
            Miralos y aprobá <strong>solo los que reconozcas como tuyos</strong>. Si dos
            se parecen y difieren en un dígito, el que aparece pocas veces es
            probablemente el mal leído: ese no se aprueba, se corrige en{' '}
            <Link href="/revisar" className="text-sky-800 underline">/revisar</Link>.
          </p>
          <ul className="mt-3 space-y-2">
            {candidatos.map((c) => (
              <li key={c.cbu} className="flex flex-wrap items-center gap-3">
                <code className="rounded bg-white px-2 py-1 tabular-nums">{c.cbu}</code>
                <span className="text-sm text-stone-600">
                  en {c.veces} comprobante{c.veces === 1 ? '' : 's'}
                </span>
                <form action={agregarCbu} className="flex items-center gap-2">
                  <input type="hidden" name="cbu" value={c.cbu} />
                  <select name="cuenta" defaultValue=""
                          className="rounded border border-stone-300 bg-white px-2 py-1 text-sm">
                    <option value="">¿de qué cuenta?</option>
                    {cuentas.map((k) => <option key={k.id} value={k.id}>{k.nombre}</option>)}
                  </select>
                  <button className="rounded bg-emerald-700 px-3 py-1 text-sm text-white hover:bg-emerald-600">
                    Es mío, aprobar
                  </button>
                </form>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rounded border border-stone-300 bg-stone-50 p-4">
        <h2 className="font-medium">Agregar uno a mano</h2>
        <form action={agregarCbu} className="mt-3 flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-stone-600">CBU o CVU — 22 dígitos</span>
            <input name="cbu" inputMode="numeric" required
                   placeholder="0000003100000000000000"
                   className="w-72 rounded border border-stone-300 bg-white px-2 py-1.5 tabular-nums" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-stone-600">Cuenta</span>
            <select name="cuenta" defaultValue=""
                    className="rounded border border-stone-300 bg-white px-2 py-1.5">
              <option value="">sin asignar</option>
              {cuentas.map((k) => <option key={k.id} value={k.id}>{k.nombre}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-stone-600">Nota (opcional)</span>
            <input name="nota" placeholder="caja de ahorro en pesos"
                   className="w-56 rounded border border-stone-300 bg-white px-2 py-1.5" />
          </label>
          <button className="rounded bg-stone-800 px-4 py-2 text-white hover:bg-stone-700">
            Agregar
          </button>
        </form>
      </section>

      <section>
        <h2 className="font-medium">Aprobados</h2>
        {propios.length === 0 ? (
          <p className="mt-2 text-sm text-stone-500">
            Todavía ninguno. Hasta que apruebes al menos uno, todos los comprobantes
            con CBU de receptor figuran como dudosos — que es lo correcto: sin lista
            de referencia no hay forma de saber si un número está bien.
          </p>
        ) : (
          <table className="mt-2 w-full border-collapse bg-white text-sm">
            <thead>
              <tr className="border-b border-stone-300 text-left">
                <th className="px-3 py-2 font-medium">CBU / CVU</th>
                <th className="px-3 py-2 font-medium">Cuenta</th>
                <th className="px-3 py-2 font-medium">Nota</th>
                <th className="px-3 py-2 font-medium">Comprobantes</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {propios.map((p) => (
                <tr key={p.id} className="border-b border-stone-200">
                  <td className="px-3 py-2 tabular-nums">{p.cbu}</td>
                  <td className="px-3 py-2">{p.cuenta ?? <span className="text-stone-400">sin asignar</span>}</td>
                  <td className="px-3 py-2 text-stone-600">{p.nota ?? '—'}</td>
                  <td className="px-3 py-2 tabular-nums">{p.usados}</td>
                  <td className="px-3 py-2 text-right">
                    <form action={borrarCbu}>
                      <input type="hidden" name="id" value={p.id} />
                      <button className="text-sm text-red-800 hover:underline">Borrar</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
