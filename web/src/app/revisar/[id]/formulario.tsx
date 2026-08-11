'use client'

import { useActionState, useRef } from 'react'
// `import type` puro: se borra al compilar, así que nombrar el tipo no arrastra
// `pg` al bundle del navegador.
import type { Campo } from '@/lib/importar-comprobantes'
import { guardarRevision, type EstadoRevision } from '../../acciones'

/**
 * El formulario de corrección. Es cliente y no servidor por una sola razón: si
 * un campo no se puede guardar, la acción devuelve cuál y la página NO navega,
 * así lo que la persona escribió sigue en pantalla. Con un redirect se perdería
 * todo lo tipeado y habría que rehacer los 16 campos.
 *
 * No importa nada de `lib/`: esos módulos arrastran `pg` y no pueden viajar al
 * navegador. Todo lo que necesita llega ya calculado por props.
 */

export type CampoVista = {
  campo: Campo
  etiqueta: string
  critico: boolean
  tipo: string
  valor: string
  ia: string
  cambiado: boolean
}

export function Formulario(
  { id, campos, filtro, motivos }:
  { id: number, campos: CampoVista[], filtro: string, motivos: string[] },
) {
  const [estado, accion, pendiente] = useActionState<EstadoRevision, FormData>(
    guardarRevision, null)

  const invalidos = new Set(estado && 'invalidos' in estado ? estado.invalidos : [])
  const nombres = campos.filter((c) => invalidos.has(c.campo)).map((c) => c.etiqueta)
  // Después de guardar mandan los motivos recién calculados; antes, los que
  // traía el comprobante al abrir la pantalla.
  const avisos = estado && 'motivos' in estado ? estado.motivos : motivos
  const seGuardo = estado !== null && 'guardado' in estado

  // Cuál de los dos botones se apretó, en un campo oculto que se escribe en el
  // `onClick`. Lo natural sería `<button name="aceptar" value="1">` y dejar que
  // el navegador mande el par del botón: no se hace porque React no renderiza
  // el `value` del botón y no está documentado que el submitter llegue al
  // FormData de `useActionState`. Un hidden SIEMPRE viaja.
  const aceptar = useRef<HTMLInputElement>(null)
  const marcar = (v: '' | '1') => () => { if (aceptar.current) aceptar.current.value = v }

  return (
    <form action={accion} className="rounded border border-stone-300 bg-white">
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="filtro" value={filtro} />
      {/* `defaultValue` y no `value`: el valor lo maneja el `onClick`, así que
          el input tiene que quedar sin controlar o React lo pisaría. */}
      <input ref={aceptar} type="hidden" name="aceptar" defaultValue="" />
      <header className="border-b border-stone-200 bg-stone-100 px-4 py-2 text-sm">
        <strong>Corregí lo que esté mal.</strong> Mirá la imagen, no lo que dice el
        modelo. Vacío significa &ldquo;no figura en el comprobante&rdquo;: no se deduce.
      </header>

      {nombres.length > 0 && (
        <p className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <strong>No se guardó nada.</strong> No se pudo interpretar{' '}
          {nombres.length === 1 ? 'el campo' : 'los campos'}{' '}
          <strong>{nombres.join(', ')}</strong>. Un valor que necesita adivinarse no se
          guarda: <span className="font-mono">$ 1.500</span> puede ser mil quinientos o
          uno con cincuenta. Corregilo y volvé a guardar — lo que escribiste sigue acá.
        </p>
      )}

      {avisos.length > 0 && (
        <div className="border-b border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <strong>
            {seGuardo ? 'Se guardó, pero algo sigue sin cerrar.' : 'Revisá estos campos.'}
          </strong>
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
            {avisos.map((m) => <li key={m} className="font-mono text-xs">{m}</li>)}
          </ul>
          <p className="mt-2">
            Mirá la imagen y corregilo. Si el comprobante <em>realmente</em> muestra eso
            —el número viene cortado o tapado—, dale a <strong>Guardar igual</strong> y
            deja de aparecer en la lista.
          </p>
        </div>
      )}

      <div className="divide-y divide-stone-200">
        {campos.map((c) => (
          <div key={c.campo} className="px-4 py-2">
            <label className="flex items-baseline gap-3 text-sm">
              <span className={`w-40 shrink-0 ${c.critico
                ? 'font-medium text-stone-800' : 'text-stone-600'}`}>
                {c.etiqueta}
                {c.critico && <span className="text-sky-700"> *</span>}
              </span>
              <input
                type={c.tipo}
                name={c.campo}
                defaultValue={c.valor}
                placeholder={c.ia ? undefined : 'lo dejó vacío'}
                className={`w-full rounded border px-2 py-1 font-mono text-sm ${
                  invalidos.has(c.campo)
                    ? 'border-red-500 bg-red-50'
                    : c.cambiado
                      ? 'border-amber-400 bg-amber-50'
                      : 'border-stone-300 bg-white'}`}
              />
            </label>
            {c.cambiado && (
              <p className="mt-1 pl-43 text-xs text-amber-800">
                la IA había puesto: {c.ia || <em>vacío</em>}
              </p>
            )}
          </div>
        ))}
      </div>

      <footer className="flex items-center justify-between border-t border-stone-200
                         bg-stone-50 px-4 py-3">
        <span className="text-xs text-stone-600">* los que la conciliación necesita</span>
        <div className="flex gap-2">
          {avisos.length > 0 && (
            // Guarda lo que esté escrito AHORA y recién después acepta la forma:
            // un retoque hecho después de leer el aviso no se pierde.
            <button type="submit" onClick={marcar('1')} disabled={pendiente}
              className="rounded border border-amber-600 px-4 py-2 text-sm font-medium
                         text-amber-900 hover:bg-amber-100 disabled:opacity-50">
              Guardar igual
            </button>
          )}
          {/* Vuelve a poner el campo en vacío: si antes se apretó "Guardar
              igual" y el guardado falló, el formulario sigue en pantalla con el
              1 puesto y este botón tiene que significar lo que dice. */}
          <button type="submit" onClick={marcar('')} disabled={pendiente}
            className="rounded bg-sky-800 px-4 py-2 text-sm font-medium text-white
                       hover:bg-sky-900 disabled:bg-stone-400">
            {pendiente ? 'Guardando…' : 'Guardar y confirmar'}
          </button>
        </div>
      </footer>
    </form>
  )
}
