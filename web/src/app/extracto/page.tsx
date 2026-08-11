'use client'

import { useActionState } from 'react'
import { subirExtracto, type EstadoSubida } from '../acciones'

export default function SubirExtracto() {
  const [estado, accion, pendiente] = useActionState<EstadoSubida, FormData>(
    subirExtracto, null)

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Subir extracto</h1>
        <p className="mt-2 text-sm text-stone-600">
          Una hoja por cuenta, con los nombres tal como están cargados. Subir el mismo
          archivo dos veces no duplica nada: las filas repetidas se descartan solas.
        </p>
      </div>

      <form action={accion} className="space-y-4 rounded border border-stone-300 bg-white p-5">
        <input
          type="file" name="archivo" accept=".xlsx,.xls" required
          className="block w-full text-sm file:mr-3 file:rounded file:border file:border-stone-400
                     file:bg-stone-100 file:px-3 file:py-1.5 file:text-sm"
        />
        <button
          disabled={pendiente}
          className="rounded bg-stone-800 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {pendiente ? 'Importando…' : 'Importar'}
        </button>
      </form>

      {estado?.ok === false && (
        <p className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {estado.error}
        </p>
      )}

      {estado?.ok && (
        <div className="space-y-3">
          <h2 className="font-medium">Resumen de la importación</h2>
          <div className="overflow-x-auto rounded border border-stone-300 bg-white">
            <table className="w-full text-sm">
              <thead className="border-b border-stone-300 bg-stone-100 text-left">
                <tr>
                  {['Cuenta', 'Leídas', 'Nuevas', 'Duplicadas', 'A revisar', 'Sin fecha', 'Desde', 'Hasta']
                    .map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {estado.resumen.map((r) => (
                  <tr key={r.cuenta} className="border-b border-stone-200 last:border-0">
                    <td className="px-3 py-2">{r.cuenta}</td>
                    <td className="px-3 py-2 tabular-nums">{r.leidas}</td>
                    <td className="px-3 py-2 tabular-nums font-medium">{r.nuevas}</td>
                    <td className="px-3 py-2 tabular-nums">{r.duplicadas}</td>
                    <td className={`px-3 py-2 tabular-nums ${r.aRevisar > 0 ? 'font-medium text-amber-800' : ''}`}>
                      {r.aRevisar}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{r.sinFecha}</td>
                    <td className="px-3 py-2">{r.fechaMin ?? '—'}</td>
                    <td className="px-3 py-2">{r.fechaMax ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {estado.resumen.some((r) => r.aRevisar > 0) && (
            <p className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              Hay filas cuyo importe no se pudo leer sin ambigüedad. Quedaron guardadas
              <strong> sin importe y marcadas para revisar</strong>: el sistema no adivina un
              número, porque un importe inventado es una acusación falsa.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
