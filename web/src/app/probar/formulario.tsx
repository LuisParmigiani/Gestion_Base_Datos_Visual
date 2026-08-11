'use client'

import { useActionState, useState } from 'react'
import { probarComprobante, type EstadoProbar } from '../acciones'

/**
 * Los 16 campos, agrupados como se leen en un comprobante.
 *
 * ponytail: las etiquetas están repetidas de `revisar/[id]/page.tsx` a propósito.
 * Nada de `lib/` se puede importar desde un componente cliente (arrastra `pg`),
 * y son 16 líneas. Si aparece un tercer consumidor, mudarlas a un módulo sin
 * dependencias de servidor y que las importen los tres.
 */
const GRUPOS = [
  {
    titulo: 'La operación',
    campos: [
      ['monto', 'Monto'], ['fecha', 'Fecha'], ['hora', 'Hora'],
      ['tipo_operacion', 'Tipo de operación'], ['moneda', 'Moneda'],
      ['coelsa_id', 'ID COELSA'],
    ],
  },
  {
    titulo: 'Quién paga',
    campos: [
      ['nombre_emisor', 'Nombre'], ['cuit_emisor', 'CUIT'],
      ['cbu_cvu_emisor', 'CBU / CVU'], ['banco_emisor', 'Banco'],
    ],
  },
  {
    titulo: 'Quién cobra',
    campos: [
      ['nombre_receptor', 'Nombre'], ['cuit_receptor', 'CUIT'],
      ['cbu_cvu_receptor', 'CBU / CVU'], ['banco_receptor', 'Banco'],
    ],
  },
  {
    titulo: 'Otros',
    campos: [['concepto', 'Concepto'], ['referencia', 'Referencia']],
  },
] as const

/** Los que deciden la conciliación. Se marcan para que salten a la vista. */
const CRITICOS = new Set(['monto', 'fecha', 'moneda', 'cuit_emisor', 'cbu_cvu_receptor', 'referencia'])

/**
 * El modelo escribe la ausencia de tres formas distintas: `''`, `'N/A'` y el
 * string `'null'`. Las tres son "no lo encontré" y ninguna es un valor: se
 * muestran como ausencia o el string `null` se lee como si fuera un dato.
 */
const sinDato = (v: string | null) =>
  v === null || ['', 'n/a', 'null', 'none'].includes(v.trim().toLowerCase())

export function Formulario({ adaptadores }: { adaptadores: string[] }) {
  const [estado, accion, pendiente] = useActionState<EstadoProbar, FormData>(
    probarComprobante, null)
  const [vistaPrevia, setVistaPrevia] = useState<string | null>(null)

  return (
    <div>
      <h1 className="text-2xl font-semibold">Probar un comprobante</h1>
      <p className="mt-2 max-w-3xl text-sm text-stone-600">
        Subí una foto y el modelo local lee los 16 campos. <strong>No se guarda nada</strong>:
        la imagen se procesa en un temporal y se borra. La base y los comprobantes revisados
        a mano quedan intactos.
      </p>

      <div className="mt-6 grid gap-8 md:grid-cols-2">
        <form action={accion} className="space-y-4">
          <div>
            <label htmlFor="imagen" className="block text-sm font-medium">
              Foto del comprobante
            </label>
            <input
              id="imagen" name="imagen" type="file" required
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => {
                const f = e.target.files?.[0]
                setVistaPrevia(f ? URL.createObjectURL(f) : null)
              }}
              className="mt-1 block w-full rounded border border-stone-300 bg-white p-2 text-sm"
            />
          </div>

          <div>
            <label htmlFor="adaptador" className="block text-sm font-medium">
              Modelo
            </label>
            <select
              id="adaptador" name="adaptador" defaultValue=""
              className="mt-1 block w-full rounded border border-stone-300 bg-white p-2 text-sm"
            >
              <option value="">Modelo base + prompt v3 (lo único medido hoy)</option>
              {adaptadores.map((a) => (
                <option key={a} value={a}>Adaptador: {a}</option>
              ))}
            </select>
            <p className="mt-1 text-xs text-stone-500">
              Los adaptadores LoRA aparecen acá solos, a medida que se entrenan. Un checkpoint
              a medio entrenar también se puede probar.
            </p>
          </div>

          <button
            type="submit" disabled={pendiente}
            className="rounded bg-stone-900 px-4 py-2 text-sm font-medium text-white disabled:bg-stone-400"
          >
            {pendiente ? 'Leyendo el comprobante…' : 'Leer el comprobante'}
          </button>

          {pendiente && (
            <p className="text-sm text-amber-700">
              Tarda entre 1 y 5 minutos: el modelo son 7 mil millones de parámetros y arranca
              de cero en cada lectura. Si hay un entrenamiento corriendo, va más lento. No
              cierres la pestaña.
            </p>
          )}

          {vistaPrevia && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={vistaPrevia} alt="El comprobante que subiste"
              className="max-h-[28rem] w-full rounded border border-stone-300 object-contain" />
          )}
        </form>

        <div>
          {estado?.ok === false && (
            <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
              {estado.error}
            </p>
          )}

          {estado?.ok && (
            <>
              <p className="text-sm text-stone-600">
                {estado.adaptador} · {estado.segundos} s
              </p>

              {Object.keys(estado.campos).length === 0 && (
                <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3">
                  <p className="text-sm font-medium text-amber-900">
                    El modelo no devolvió JSON. Esto es lo que sí dijo:
                  </p>
                  <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs text-amber-900">
                    {estado.sinParsear ?? '(nada)'}
                  </pre>
                </div>
              )}

              {GRUPOS.map((g) => (
                <div key={g.titulo} className="mt-4">
                  <h2 className="text-sm font-semibold text-stone-500">{g.titulo}</h2>
                  <dl className="mt-1 divide-y divide-stone-200 border-t border-stone-200">
                    {g.campos.map(([campo, etiqueta]) => {
                      const v = estado.campos[campo]
                      const vacio = sinDato(v ?? null)
                      return (
                        <div key={campo} className="flex gap-4 py-1.5 text-sm">
                          <dt className={`w-40 shrink-0 ${CRITICOS.has(campo)
                            ? 'font-medium text-stone-900' : 'text-stone-500'}`}>
                            {etiqueta}
                          </dt>
                          <dd className={vacio ? 'text-stone-400' : 'break-all'}>
                            {vacio ? '— no lo encontró —' : v}
                          </dd>
                        </div>
                      )
                    })}
                  </dl>
                </div>
              ))}

              <p className="mt-4 text-xs text-stone-500">
                En negrita, los campos que deciden la conciliación. Un campo vacío quiere decir
                que el modelo no lo encontró, no que el comprobante no lo tenga. El modelo base
                acierta ~65% de los campos y su falla más común es <strong>inventar</strong> los
                datos del emisor: verificá CBU y CUIT contra la imagen antes de creerles.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
