/**
 * Los seis estados, con su explicación al lado.
 *
 * El texto importa tanto como el color: "no verificable" y "sospechoso" se
 * parecen si uno solo mira una etiqueta, y confundirlos es acusar a alguien
 * que pagó bien.
 */
export const ESTADOS = {
  verificado: {
    etiqueta: 'Verificado', color: 'bg-emerald-100 text-emerald-900 border-emerald-300',
    que: 'El comprobante tiene su movimiento en el extracto', hacer: 'Nada, la plata entró',
  },
  sospechoso: {
    etiqueta: 'Sospechoso', color: 'bg-red-100 text-red-900 border-red-300',
    que: 'La cuenta está cargada y el extracto cubre esa fecha, pero el movimiento no existe',
    hacer: 'Revisar en serio',
  },
  no_verificable: {
    etiqueta: 'No verificable', color: 'bg-amber-100 text-amber-900 border-amber-300',
    que: 'La cuenta no está cargada, o el extracto no cubre esa fecha',
    hacer: 'No opinar. Falta información',
  },
  duplicado: {
    etiqueta: 'Duplicado', color: 'bg-violet-100 text-violet-900 border-violet-300',
    que: 'Dos comprobantes distintos reclaman el mismo movimiento',
    hacer: 'Uno de los dos es un reenvío',
  },
  ambiguo: {
    etiqueta: 'Ambiguo', color: 'bg-sky-100 text-sky-900 border-sky-300',
    que: 'Varios movimientos podrían corresponder al mismo comprobante',
    hacer: 'Decisión humana',
  },
  sin_comprobante: {
    etiqueta: 'Sin comprobante', color: 'bg-stone-200 text-stone-800 border-stone-400',
    que: 'Entró plata al banco y nadie mandó comprobante', hacer: 'Averiguar de quién es',
  },
} as const

export type ClaveEstado = keyof typeof ESTADOS

export function Etiqueta({ estado }: { estado: string }) {
  const e = ESTADOS[estado as ClaveEstado]
  if (!e) return <span className="text-stone-500">{estado}</span>
  return (
    <span
      title={`${e.que}. ${e.hacer}.`}
      className={`inline-block whitespace-nowrap rounded border px-2 py-0.5 text-xs font-medium ${e.color}`}
    >
      {e.etiqueta}
    </span>
  )
}

// ponytail: `Number` acá es SOLO para mostrar. Nunca se hace una cuenta con
// esto: los importes viajan como string y se comparan como enteros de centavos.
export const plata = (v: string | null) =>
  v === null
    ? '—'
    : new Intl.NumberFormat('es-AR', { style: 'currency', currency: 'ARS' }).format(Number(v))
