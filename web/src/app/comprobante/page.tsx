'use client'

import { useActionState } from 'react'
import { guardarComprobante, type EstadoComprobante } from '../acciones'
import { Etiqueta } from '../estados'

/** Los 16 campos, agrupados como se leen en un comprobante. */
const GRUPOS = [
  {
    titulo: 'La operación',
    campos: [
      { name: 'monto', label: 'Monto', tipo: 'text', ayuda: 'Solo el número: 250000.00' },
      { name: 'fecha', label: 'Fecha', tipo: 'date' },
      { name: 'hora', label: 'Hora', tipo: 'time' },
      { name: 'tipo_operacion', label: 'Tipo de operación', tipo: 'text' },
      { name: 'moneda', label: 'Moneda', tipo: 'text' },
      { name: 'coelsa_id', label: 'ID COELSA', tipo: 'text', ayuda: 'Si está, da certeza total' },
    ],
  },
  {
    titulo: 'Quién paga',
    campos: [
      { name: 'nombre_emisor', label: 'Nombre', tipo: 'text' },
      { name: 'cuit_emisor', label: 'CUIT', tipo: 'text', ayuda: 'La clave de cruce principal' },
      { name: 'cbu_cvu_emisor', label: 'CBU / CVU', tipo: 'text' },
      { name: 'banco_emisor', label: 'Banco', tipo: 'text' },
    ],
  },
  {
    titulo: 'Quién cobra',
    campos: [
      { name: 'nombre_receptor', label: 'Nombre', tipo: 'text' },
      { name: 'cuit_receptor', label: 'CUIT', tipo: 'text' },
      { name: 'cbu_cvu_receptor', label: 'CBU / CVU', tipo: 'text',
        ayuda: 'Decide contra qué cuenta se cruza' },
      { name: 'banco_receptor', label: 'Banco', tipo: 'text' },
    ],
  },
  {
    titulo: 'Otros',
    campos: [
      { name: 'concepto', label: 'Concepto', tipo: 'text' },
      { name: 'referencia', label: 'Referencia', tipo: 'text' },
    ],
  },
] as const

export default function CargarComprobante() {
  const [estado, accion, pendiente] = useActionState<EstadoComprobante, FormData>(
    guardarComprobante, null)

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Cargar comprobante</h1>
        <p className="mt-2 text-sm text-stone-600">
          Los campos vacíos quedan vacíos: no se completan por defecto. Al guardar, el
          comprobante se cruza contra el extracto y aparece en el tablero con su estado.
        </p>
      </div>

      {estado?.ok === false && (
        <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {estado.error}
        </p>
      )}
      {estado?.ok && (
        <p className="flex flex-wrap items-center gap-2 rounded border border-emerald-300 bg-emerald-50 p-3 text-sm">
          Guardado como comprobante #{estado.id}. Quedó en <Etiqueta estado={estado.estado} />
        </p>
      )}

      <form action={accion} className="space-y-6">
        <div className="rounded border border-stone-300 bg-white p-5">
          <label className="block text-sm font-medium">Imagen del comprobante</label>
          <input
            type="file" name="imagen" accept="image/*,.pdf" required
            className="mt-2 block w-full text-sm file:mr-3 file:rounded file:border
                       file:border-stone-400 file:bg-stone-100 file:px-3 file:py-1.5"
          />
          <p className="mt-2 text-xs text-stone-600">
            Se guarda en esta máquina. Si la misma imagen ya se cargó, se rechaza.
          </p>
        </div>

        {GRUPOS.map((g) => (
          <fieldset key={g.titulo} className="rounded border border-stone-300 bg-white p-5">
            <legend className="px-2 text-sm font-medium">{g.titulo}</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {g.campos.map((c) => (
                <label key={c.name} className="block text-sm">
                  <span className="font-medium">
                    {c.label}
                    {(c.name === 'monto' || c.name === 'fecha') && (
                      <span className="text-red-700"> *</span>
                    )}
                  </span>
                  <input
                    type={c.tipo} name={c.name}
                    required={c.name === 'monto' || c.name === 'fecha'}
                    className="mt-1 w-full rounded border border-stone-400 px-2 py-1.5"
                  />
                  {'ayuda' in c && <span className="mt-1 block text-xs text-stone-600">{c.ayuda}</span>}
                </label>
              ))}
            </div>
          </fieldset>
        ))}

        <button
          disabled={pendiente}
          className="rounded bg-stone-800 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {pendiente ? 'Guardando…' : 'Guardar y conciliar'}
        </button>
      </form>
    </div>
  )
}
