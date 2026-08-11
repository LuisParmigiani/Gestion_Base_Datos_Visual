/**
 * Fixtures del motor de conciliación (F3).
 *
 * Los 52 comprobantes reales son de otra fuente y otro período: no cruzan con
 * el extracto. Así que el motor se prueba con datos fabricados donde la
 * respuesta correcta se conoce de antemano.
 *
 * Todo lo de acá es **inventado**: CUIT, CBU, COELSA, nombres y montos. No hay
 * un solo dato real, por eso este archivo puede ir al repo.
 *
 * Fechas elegidas a propósito sobre junio de 2026, verificadas:
 *   05/06 viernes · 06/06 sábado · 07/06 domingo · 08/06 lunes
 */

import type { Estado } from './motor.ts'

export type CuentaFixture = {
  nombre: string
  cbu: string
  /** Cobertura del extracto cargado. `null` = la cuenta existe pero no se subió extracto. */
  fechaMin: string | null
  fechaMax: string | null
}

export type MovimientoFixture = {
  id: number
  cuenta: string
  fecha: string
  importe: string
  esIngreso: boolean
  cuitEmisor: string | null
  coelsaId: string | null
  descripcion: string
}

export type ComprobanteFixture = {
  id: number
  /** Qué prueba este caso, en castellano. Sin esto la fixture no se entiende. */
  caso: string
  monto: string
  fecha: string
  hora: string | null
  cuitEmisor: string | null
  cbuReceptor: string
  coelsaId: string | null
  estadoEsperado: Estado
  /** Escalón de la cascada que debería resolverlo. `null` si no se resuelve. */
  reglaEsperada: 1 | 2 | 3 | null
  confianzaEsperada: 'alta' | 'media' | null
  movimientoEsperado: number | null
  /** Solo para el ambiguo: los movimientos entre los que hay que elegir. */
  candidatosEsperados: number[]
}

const CBU_SUCESION = '0170099220000012345678'
const CBU_QUIQUE = '0170099220000087654321'
const CBU_MARIELA = '0170099220000011223344'
/** Una cuenta que no es nuestra. El caso Mercado Pago del README. */
const CBU_AJENO = '0000003100099999999999'

export const CUENTAS: CuentaFixture[] = [
  { nombre: 'SUCESION', cbu: CBU_SUCESION, fechaMin: '2026-03-02', fechaMax: '2026-06-30' },
  { nombre: 'QUIQUE', cbu: CBU_QUIQUE, fechaMin: '2026-03-02', fechaMax: '2026-06-30' },
  // Existe como cuenta, pero nunca se le subió un extracto: sin cobertura no
  // hay veredicto posible. Es distinto de "la cuenta no es nuestra".
  { nombre: 'MARIELA', cbu: CBU_MARIELA, fechaMin: null, fechaMax: null },
]

export const MOVIMIENTOS: MovimientoFixture[] = [
  { id: 1, cuenta: 'SUCESION', fecha: '2026-06-02', importe: '250000.00', esIngreso: true,
    cuitEmisor: '27123456789', coelsaId: 'AAAA1111BBBB2222CCCC33',
    descripcion: 'ING TRANSF:AAAA1111BBBB2222CCCC33 27123456789 GOMEZ/A' },

  { id: 2, cuenta: 'SUCESION', fecha: '2026-06-03', importe: '180500.50', esIngreso: true,
    cuitEmisor: '20111222333', coelsaId: null,
    descripcion: 'ING TRANSF 20111222333 PEREZ, J' },

  // Lunes. Le corresponde un comprobante del viernes anterior a las 21:46.
  { id: 3, cuenta: 'SUCESION', fecha: '2026-06-08', importe: '95000.00', esIngreso: true,
    cuitEmisor: '30555666777', coelsaId: null,
    descripcion: 'ING TRANSF 30555666777 SRL LOGIST' },

  // Sin CUIT en la descripción: solo se puede cruzar por importe y fecha.
  { id: 4, cuenta: 'SUCESION', fecha: '2026-06-10', importe: '42000.00', esIngreso: true,
    cuitEmisor: null, coelsaId: null, descripcion: 'TEF DEPOSITO' },

  // Estos dos son idénticos en importe y fecha: cualquier comprobante que les
  // apunte sin CUIT es irresoluble por máquina.
  { id: 5, cuenta: 'SUCESION', fecha: '2026-06-11', importe: '77000.00', esIngreso: true,
    cuitEmisor: null, coelsaId: null, descripcion: 'TEF DEPOSITO' },
  { id: 6, cuenta: 'SUCESION', fecha: '2026-06-11', importe: '77000.00', esIngreso: true,
    cuitEmisor: null, coelsaId: null, descripcion: 'TEF DEPOSITO' },

  // Un solo movimiento que dos comprobantes van a reclamar.
  { id: 7, cuenta: 'SUCESION', fecha: '2026-06-12', importe: '310000.00', esIngreso: true,
    cuitEmisor: '27999888777', coelsaId: null,
    descripcion: 'ING TRANSF 27999888777 ALONSO, H' },

  // Entró plata y nadie mandó comprobante.
  { id: 8, cuenta: 'SUCESION', fecha: '2026-06-15', importe: '500000.00', esIngreso: true,
    cuitEmisor: '20444555666', coelsaId: null,
    descripcion: 'ING TRANSF 20444555666 PODESTA/M' },

  // Egreso: se guarda pero se excluye de la conciliación. Un comprobante que
  // coincida en importe y fecha NO puede matchearlo.
  { id: 9, cuenta: 'SUCESION', fecha: '2026-06-15', importe: '-112340.06', esIngreso: false,
    cuitEmisor: null, coelsaId: null, descripcion: 'MOVISTAR FACTURA' },

  // En OTRA cuenta. Un comprobante dirigido a SUCESION no puede tomarlo.
  { id: 10, cuenta: 'QUIQUE', fecha: '2026-06-09', importe: '60000.00', esIngreso: true,
    cuitEmisor: '23777888999', coelsaId: null,
    descripcion: 'ING TRANSF 23777888999 ORSI/JAVI' },
]

export const COMPROBANTES: ComprobanteFixture[] = [
  {
    id: 1,
    caso: 'COELSA idéntico: certeza total, corta en el primer escalón',
    monto: '250000.00', fecha: '2026-06-02', hora: '10:15',
    cuitEmisor: '27123456789', cbuReceptor: CBU_SUCESION,
    coelsaId: 'AAAA1111BBBB2222CCCC33',
    estadoEsperado: 'verificado', reglaEsperada: 1, confianzaEsperada: 'alta',
    movimientoEsperado: 1, candidatosEsperados: [],
  },
  {
    id: 2,
    caso: 'Sin COELSA: cruza por CUIT emisor + importe exacto + misma fecha',
    monto: '180500.50', fecha: '2026-06-03', hora: '14:02',
    cuitEmisor: '20111222333', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'verificado', reglaEsperada: 2, confianzaEsperada: 'alta',
    movimientoEsperado: 2, candidatosEsperados: [],
  },
  {
    id: 3,
    caso: 'Viernes 21:46 que impacta el lunes: la tolerancia es de días HÁBILES, ' +
          'no de días corridos. Con ±1 día corrido este caso fallaría',
    monto: '95000.00', fecha: '2026-06-05', hora: '21:46',
    cuitEmisor: '30555666777', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'verificado', reglaEsperada: 2, confianzaEsperada: 'alta',
    movimientoEsperado: 3, candidatosEsperados: [],
  },
  {
    id: 4,
    caso: 'Sin CUIT: importe y fecha con un solo candidato. Confianza media, ' +
          'no alta, porque el emisor no está confirmado',
    monto: '42000.00', fecha: '2026-06-10', hora: null,
    cuitEmisor: null, cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'verificado', reglaEsperada: 3, confianzaEsperada: 'media',
    movimientoEsperado: 4, candidatosEsperados: [],
  },
  {
    id: 5,
    caso: 'Sin CUIT y dos movimientos idénticos: no se resuelve solo, decide una persona',
    monto: '77000.00', fecha: '2026-06-11', hora: null,
    cuitEmisor: null, cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'ambiguo', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [5, 6],
  },
  {
    id: 6,
    caso: 'Primero de los dos que reclaman el mismo movimiento',
    monto: '310000.00', fecha: '2026-06-12', hora: '09:30',
    cuitEmisor: '27999888777', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'duplicado', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: 7, candidatosEsperados: [],
  },
  {
    id: 7,
    caso: 'Segundo que reclama el mismo movimiento: uno de los dos es un reenvío',
    monto: '310000.00', fecha: '2026-06-12', hora: '09:30',
    cuitEmisor: '27999888777', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'duplicado', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: 7, candidatosEsperados: [],
  },
  {
    id: 8,
    caso: 'Cuenta cargada y fecha dentro de la cobertura, pero el movimiento no ' +
          'existe. El sistema pudo mirar y no lo vio: sospechoso',
    monto: '33333.00', fecha: '2026-06-04', hora: '11:00',
    cuitEmisor: '27000111222', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'sospechoso', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 9,
    caso: 'La cuenta destino no es nuestra (el caso Mercado Pago del README). ' +
          'No se opina: falta información',
    monto: '250000.00', fecha: '2026-06-02', hora: '21:46',
    cuitEmisor: '27062108679', cbuReceptor: CBU_AJENO, coelsaId: null,
    estadoEsperado: 'no_verificable', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 10,
    caso: 'La cuenta es nuestra pero nunca se le subió extracto: sin cobertura ' +
          'no hay veredicto',
    monto: '18000.00', fecha: '2026-06-04', hora: null,
    cuitEmisor: '20999888777', cbuReceptor: CBU_MARIELA, coelsaId: null,
    estadoEsperado: 'no_verificable', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 11,
    caso: 'Cuenta cargada, pero la fecha cae fuera del rango del extracto ' +
          '(termina el 30/06). No se opina',
    monto: '71000.00', fecha: '2026-07-05', hora: null,
    cuitEmisor: '20111222333', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'no_verificable', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 12,
    caso: 'Un centavo de diferencia con el movimiento 8. El importe se compara ' +
          'exacto: no matchea, y el movimiento 8 sigue sin comprobante',
    monto: '500000.01', fecha: '2026-06-15', hora: null,
    cuitEmisor: '20444555666', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'sospechoso', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 13,
    caso: 'Coincide en importe y fecha con un EGRESO. Los egresos se excluyen ' +
          'de la conciliación: no puede matchear',
    monto: '112340.06', fecha: '2026-06-15', hora: null,
    cuitEmisor: null, cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'sospechoso', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
  {
    id: 14,
    caso: 'Coincide en importe, fecha y CUIT con el movimiento 10, pero ese ' +
          'movimiento está en OTRA cuenta. La cuenta destino tiene que coincidir',
    monto: '60000.00', fecha: '2026-06-09', hora: null,
    cuitEmisor: '23777888999', cbuReceptor: CBU_SUCESION, coelsaId: null,
    estadoEsperado: 'sospechoso', reglaEsperada: null, confianzaEsperada: null,
    movimientoEsperado: null, candidatosEsperados: [],
  },
]

/**
 * Ingresos que ningún comprobante reclama.
 *
 * El 5 y el 6 quedan afuera a propósito: son los candidatos del comprobante
 * ambiguo. Listarlos como "sin comprobante" mientras la ambigüedad está sin
 * resolver diría dos cosas contradictorias sobre el mismo movimiento.
 *
 * El 9 tampoco está: es un egreso y no entra nunca en la conciliación.
 */
export const SIN_COMPROBANTE_ESPERADOS = [8, 10]
