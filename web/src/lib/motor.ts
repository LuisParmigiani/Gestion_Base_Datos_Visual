export type Estado =
  | 'verificado' | 'sospechoso' | 'no_verificable' | 'duplicado' | 'ambiguo'

export type Cuenta = {
  nombre: string
  cbu: string
  /** Cobertura del extracto. `null` = la cuenta existe pero no se le subió extracto. */
  fechaMin: string | null
  fechaMax: string | null
}

export type Movimiento = {
  id: number
  cuenta: string
  fecha: string
  /** `null` cuando el importe del extracto era irresoluble. Nunca matchea. */
  importe: string | null
  esIngreso: boolean
  cuitEmisor: string | null
  coelsaId: string | null
}

export type Comprobante = {
  id: number
  monto: string
  fecha: string
  cuitEmisor: string | null
  cbuReceptor: string
  coelsaId: string | null
}

export type Veredicto = {
  estado: Estado
  confianza: 'alta' | 'media' | null
  /** Escalón de la cascada que lo resolvió. `null` si no se resolvió. */
  regla: 1 | 2 | 3 | null
  movimientoId: number | null
  /** Solo para el ambiguo: entre estos hay que elegir a mano. */
  candidatos: number[]
}

export type Conciliacion = {
  veredictos: Map<number, Veredicto>
  /** Ingresos que ningún comprobante reclama. */
  sinComprobante: number[]
}

/**
 * Días hábiles de tolerancia entre la fecha del comprobante y la del
 * movimiento. Una transferencia de las 21:46 impacta al día siguiente, y un
 * viernes a la noche corre al lunes.
 */
export const TOLERANCIA_DIAS_HABILES = 1

/**
 * Importe a centavos, como entero. Nunca `number`: `0.1 + 0.2 !== 0.3` y esto
 * es plata. Devuelve `null` si el texto no es un importe con hasta 2 decimales.
 */
function centavos(valor: string): bigint | null {
  const m = valor.match(/^(-?)(\d+)(?:[.](\d{1,2}))?$/)
  if (!m) return null
  const [, signo, entero, decimales = ''] = m
  return BigInt(signo + entero + decimales.padEnd(2, '0'))
}

const esFinDeSemana = (d: Date) => d.getUTCDay() === 0 || d.getUTCDay() === 6

/**
 * Días hábiles entre dos fechas ISO, sin importar el orden.
 *
 * ponytail: sin calendario de feriados. Una tabla de feriados argentinos se
 * desactualiza sola, y el error que produce su ausencia es el seguro: un
 * feriado hace que un hueco de 1 día hábil parezca de 2, y el comprobante cae
 * en `sospechoso` — que pide revisión humana — en vez de `verificado`.
 */
export function diasHabiles(a: string, b: string): number {
  const [desde, hasta] = a <= b ? [a, b] : [b, a]
  const cursor = new Date(`${desde}T00:00:00Z`)
  const fin = new Date(`${hasta}T00:00:00Z`)
  if (Number.isNaN(cursor.getTime()) || Number.isNaN(fin.getTime())) return Infinity
  // Corte de seguridad: nada que esté a más de 30 días corridos puede estar
  // dentro de la tolerancia, y así el bucle no se va de viaje.
  if (fin.getTime() - cursor.getTime() > 30 * 86_400_000) return Infinity

  let habiles = 0
  while (cursor < fin) {
    cursor.setUTCDate(cursor.getUTCDate() + 1)
    if (!esFinDeSemana(cursor)) habiles++
  }
  return habiles
}

/** El último día en que el dinero de un comprobante todavía podría impactar. */
function ultimoDiaPosible(fecha: string): string {
  const cursor = new Date(`${fecha}T00:00:00Z`)
  let restantes = TOLERANCIA_DIAS_HABILES
  while (restantes > 0) {
    cursor.setUTCDate(cursor.getUTCDate() + 1)
    if (!esFinDeSemana(cursor)) restantes--
  }
  return cursor.toISOString().slice(0, 10)
}

const dentroDeTolerancia = (a: string, b: string) =>
  diasHabiles(a, b) <= TOLERANCIA_DIAS_HABILES

/**
 * La cascada del README. Se corta en el primer escalón que da resultado.
 *
 * Trabaja sobre el lote entero y no de a un comprobante, porque dos de los
 * seis estados solo existen mirando el conjunto: `duplicado` necesita ver que
 * otro comprobante reclama el mismo movimiento, y `sin comprobante` necesita
 * ver que ninguno reclamó ese ingreso.
 */
export function conciliar(
  comprobantes: Comprobante[], movimientos: Movimiento[], cuentas: Cuenta[],
): Conciliacion {
  const porCbu = new Map(cuentas.map((c) => [c.cbu, c]))
  // Los egresos quedan afuera de todo: no se concilian ni se reclaman.
  const ingresos = movimientos.filter((m) => m.esIngreso)

  const veredictos = new Map<number, Veredicto>()
  for (const c of comprobantes) veredictos.set(c.id, juzgar(c, ingresos, porCbu))

  // Un movimiento reclamado por dos comprobantes deja a los dos en duda: uno
  // de los dos es un reenvío, y la máquina no puede saber cuál.
  const reclamos = new Map<number, number[]>()
  for (const [id, v] of veredictos) {
    if (v.estado !== 'verificado' || v.movimientoId === null) continue
    reclamos.set(v.movimientoId, [...(reclamos.get(v.movimientoId) ?? []), id])
  }
  for (const [movimientoId, ids] of reclamos) {
    if (ids.length < 2) continue
    for (const id of ids) {
      veredictos.set(id, {
        estado: 'duplicado', confianza: null, regla: null, movimientoId, candidatos: [],
      })
    }
  }

  // Un candidato de un ambiguo no es "sin comprobante": mientras la ambigüedad
  // esté sin resolver, decir las dos cosas del mismo movimiento se contradice.
  const alcanzados = new Set<number>()
  for (const v of veredictos.values()) {
    if (v.movimientoId !== null) alcanzados.add(v.movimientoId)
    for (const id of v.candidatos) alcanzados.add(id)
  }

  return {
    veredictos,
    sinComprobante: ingresos.filter((m) => !alcanzados.has(m.id)).map((m) => m.id),
  }
}

function juzgar(
  c: Comprobante, ingresos: Movimiento[], porCbu: Map<string, Cuenta>,
): Veredicto {
  const sinResolver = (estado: Estado, candidatos: number[] = []): Veredicto =>
    ({ estado, confianza: null, regla: null, movimientoId: null, candidatos })

  const cuenta = porCbu.get(c.cbuReceptor)
  // La cuenta destino no es ninguna de las nuestras: el caso Mercado Pago.
  if (!cuenta) return sinResolver('no_verificable')
  // La cuenta es nuestra, pero nunca se le subió un extracto.
  if (cuenta.fechaMin === null || cuenta.fechaMax === null) return sinResolver('no_verificable')

  const propios = ingresos.filter((m) => m.cuenta === cuenta.nombre)

  // 1 · COELSA idéntico. Identifica la transferencia: gana sobre todo lo demás.
  // Se compara plegando mayúsculas: el extracto lo trae siempre en mayúsculas y
  // la IA lo transcribe como lo ve. Perder el escalón más confiable de los tres
  // por una diferencia de tipeo sería el peor cambio posible por la razón más
  // tonta.
  if (c.coelsaId) {
    const buscado = c.coelsaId.toLowerCase()
    const m = propios.find((x) => x.coelsaId?.toLowerCase() === buscado)
    if (m) return { estado: 'verificado', confianza: 'alta', regla: 1, movimientoId: m.id, candidatos: [] }
  }

  const monto = centavos(c.monto)
  const coincide = (m: Movimiento) => {
    const importe = m.importe === null ? null : centavos(m.importe)
    return monto !== null && importe !== null && importe === monto
      && dentroDeTolerancia(c.fecha, m.fecha)
  }

  // 2 · CUIT emisor + importe exacto + fecha dentro de la tolerancia.
  if (c.cuitEmisor) {
    const porCuit = propios.filter((m) => m.cuitEmisor === c.cuitEmisor && coincide(m))
    if (porCuit.length === 1) {
      return { estado: 'verificado', confianza: 'alta', regla: 2, movimientoId: porCuit[0].id, candidatos: [] }
    }
    if (porCuit.length > 1) return sinResolver('ambiguo', porCuit.map((m) => m.id))
  }

  // 3 · Importe + fecha, sin usar el CUIT.
  //
  // Se cae acá también cuando el comprobante SÍ trae CUIT pero ningún
  // movimiento lo tiene: el extracto solo deja parsear el CUIT en el 90-93% de
  // las filas, y exigirlo en los dos lados dejaría el resto sin conciliar nunca.
  //
  // Lo que no se tolera es que los dos tengan CUIT y sean distintos: verificar
  // el pago de una persona con el movimiento de otra es el peor error posible.
  const candidatos = propios.filter((m) =>
    coincide(m) && !(c.cuitEmisor && m.cuitEmisor && m.cuitEmisor !== c.cuitEmisor))
  if (candidatos.length === 1) {
    return { estado: 'verificado', confianza: 'media', regla: 3, movimientoId: candidatos[0].id, candidatos: [] }
  }
  if (candidatos.length > 1) return sinResolver('ambiguo', candidatos.map((m) => m.id))

  // 4 · Sin candidatos. Solo se dice "sospechoso" cuando el sistema puede
  // probar que tenía cómo verlo: la fecha del comprobante Y el último día en
  // que su dinero podría haber impactado tienen que estar dentro del extracto.
  const cubierto = c.fecha >= cuenta.fechaMin && ultimoDiaPosible(c.fecha) <= cuenta.fechaMax
  return sinResolver(cubierto ? 'sospechoso' : 'no_verificable')
}
