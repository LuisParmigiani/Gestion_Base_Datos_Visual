import { test } from 'node:test'
import assert from 'node:assert/strict'
import { CUENTAS, MOVIMIENTOS, COMPROBANTES, SIN_COMPROBANTE_ESPERADOS } from './fixtures.ts'
import { conciliar, type Comprobante, type Movimiento, type Cuenta } from './motor.ts'

// El motor es el único componente donde un error acusa a una persona honesta.
// Los 14 casos de F3 traen su respuesta escrita de antemano; abajo de eso hay
// casos armados a mano para los bordes que las fixtures no cubren.

const resultado = conciliar(COMPROBANTES, MOVIMIENTOS, CUENTAS)

for (const c of COMPROBANTES) {
  test(`comprobante ${c.id}: ${c.caso}`, () => {
    const v = resultado.veredictos.get(c.id)
    assert.ok(v, `el motor no emitió veredicto para el comprobante ${c.id}`)
    assert.equal(v.estado, c.estadoEsperado)
    assert.equal(v.regla, c.reglaEsperada)
    assert.equal(v.confianza, c.confianzaEsperada)
    assert.equal(v.movimientoId, c.movimientoEsperado)
    assert.deepEqual([...v.candidatos].sort(), [...c.candidatosEsperados].sort())
  })
}

test('los ingresos que nadie reclamó se listan, y solo esos', () => {
  assert.deepEqual([...resultado.sinComprobante].sort(), [...SIN_COMPROBANTE_ESPERADOS].sort())
})

// ─── Bordes que las fixtures no cubren ─────────────────────────────────

const CBU = '0170099220000012345678'
const cuenta = (fechaMin = '2026-06-01', fechaMax = '2026-06-30'): Cuenta[] =>
  [{ nombre: 'UNA', cbu: CBU, fechaMin, fechaMax }]

const mov = (p: Partial<Movimiento> = {}): Movimiento => ({
  id: 1, cuenta: 'UNA', fecha: '2026-06-10', importe: '1000.00', esIngreso: true,
  cuitEmisor: null, coelsaId: null, ...p,
})

const comp = (p: Partial<Comprobante> = {}): Comprobante => ({
  id: 1, monto: '1000.00', fecha: '2026-06-10', cuitEmisor: null,
  cbuReceptor: CBU, coelsaId: null, ...p,
})

const veredicto = (c: Comprobante, ms: Movimiento[], cs = cuenta()) =>
  conciliar([c], ms, cs).veredictos.get(c.id)!

test('un comprobante con CUIT matchea un movimiento cuyo CUIT no se pudo parsear', () => {
  // El 7-10% de las filas del extracto no tiene CUIT parseable. Si el motor
  // exigiera CUIT en los dos lados, esas filas nunca se podrían conciliar.
  const v = veredicto(comp({ cuitEmisor: '27123456789' }), [mov({ cuitEmisor: null })])
  assert.equal(v.estado, 'verificado')
  assert.equal(v.regla, 3, 'debería caer al escalón 3, no al 2')
  assert.equal(v.confianza, 'media', 'sin CUIT confirmado la confianza no puede ser alta')
})

test('un CUIT que se contradice NO matchea, aunque importe y fecha coincidan', () => {
  // Es el peor error posible: verificar el pago de una persona con el
  // movimiento de otra. Coincidir en importe y fecha no alcanza.
  const v = veredicto(comp({ cuitEmisor: '27123456789' }), [mov({ cuitEmisor: '20999888777' })])
  assert.equal(v.estado, 'sospechoso')
  assert.equal(v.movimientoId, null)
})

test('el COELSA matchea aunque venga en minúsculas', () => {
  // El ID COELSA es alfanumérico y el extracto lo trae siempre en mayúsculas,
  // pero la IA lo transcribe como lo ve: 4 de los comprobantes cargados lo
  // tienen en minúsculas. Sin plegar, el escalón 1 —el más confiable de los
  // tres— se saltea por una diferencia de tipeo. Decisión del 2026-08-11.
  const v = veredicto(comp({ coelsaId: 'abc123xyz' }), [mov({ coelsaId: 'ABC123XYZ' })])
  assert.equal(v.regla, 1, 'debería resolver por COELSA, no caer a monto+fecha')
  assert.equal(v.confianza, 'alta')
})

test('el importe se compara exacto: un centavo de más no matchea', () => {
  assert.equal(veredicto(comp({ monto: '1000.01' }), [mov()]).estado, 'sospechoso')
})

test('el importe compara 250000 con 250000.00 como iguales', () => {
  assert.equal(veredicto(comp({ monto: '250000' }), [mov({ importe: '250000.00' })]).estado,
    'verificado')
})

test('un movimiento sin importe (ambiguo en el extracto) no matchea nada', () => {
  assert.equal(veredicto(comp(), [mov({ importe: null })]).estado, 'sospechoso')
})

// ─── La tolerancia de días hábiles ─────────────────────────────────────

test('el viernes a la noche impacta el lunes: un día hábil de diferencia', () => {
  const v = veredicto(comp({ fecha: '2026-06-05' }), [mov({ fecha: '2026-06-08' })])
  assert.equal(v.estado, 'verificado', 'viernes → lunes es 1 día hábil, no 3 corridos')
})

test('el viernes no llega hasta el martes: son dos días hábiles', () => {
  assert.equal(veredicto(comp({ fecha: '2026-06-05' }), [mov({ fecha: '2026-06-09' })]).estado,
    'sospechoso')
})

test('el mismo día matchea', () => {
  assert.equal(veredicto(comp({ fecha: '2026-06-10' }), [mov({ fecha: '2026-06-10' })]).estado,
    'verificado')
})

test('la tolerancia va para los dos lados', () => {
  assert.equal(veredicto(comp({ fecha: '2026-06-11' }), [mov({ fecha: '2026-06-10' })]).estado,
    'verificado')
})

// ─── El estado que no se puede equivocar ───────────────────────────────

test('sin cobertura no hay veredicto: la cuenta cargada pero sin extracto', () => {
  const v = veredicto(comp(), [], [{ nombre: 'UNA', cbu: CBU, fechaMin: null, fechaMax: null }])
  assert.equal(v.estado, 'no_verificable', 'sin extracto no se puede acusar a nadie')
})

test('una cuenta que no es nuestra da no_verificable, nunca sospechoso', () => {
  const v = veredicto(comp({ cbuReceptor: '0000003100099999999999' }), [])
  assert.equal(v.estado, 'no_verificable')
})

test('si el dinero podría caer fuera del extracto, no se opina', () => {
  // Comprobante del último día cubierto: su movimiento podría impactar el día
  // hábil siguiente, que el extracto ya no muestra. No se puede probar que
  // faltó, así que no se dice "sospechoso".
  const v = veredicto(comp({ fecha: '2026-06-30' }), [], cuenta('2026-06-01', '2026-06-30'))
  assert.equal(v.estado, 'no_verificable')
})

test('un día antes del borde sí se puede juzgar', () => {
  const v = veredicto(comp({ fecha: '2026-06-25' }), [], cuenta('2026-06-01', '2026-06-30'))
  assert.equal(v.estado, 'sospechoso')
})

// ─── Reglas que se pisan ───────────────────────────────────────────────

test('el COELSA gana aunque el importe no coincida', () => {
  // El COELSA identifica la transferencia. Si el importe difiere, el problema
  // está en la extracción del comprobante, no en que sea otra transferencia.
  const v = veredicto(
    comp({ coelsaId: 'AAAA1111BBBB2222CCCC33', monto: '9999.00' }),
    [mov({ coelsaId: 'AAAA1111BBBB2222CCCC33' })])
  assert.equal(v.estado, 'verificado')
  assert.equal(v.regla, 1)
})

test('un movimiento de otra cuenta nunca es candidato', () => {
  const v = veredicto(comp(), [mov({ cuenta: 'OTRA' })])
  assert.equal(v.estado, 'sospechoso')
})

test('un egreso nunca es candidato ni figura como sin comprobante', () => {
  const egreso = mov({ importe: '-1000.00', esIngreso: false })
  const r = conciliar([comp({ monto: '1000.00' })], [egreso], cuenta())
  assert.equal(r.veredictos.get(1)!.estado, 'sospechoso')
  assert.deepEqual(r.sinComprobante, [])
})

test('dos candidatos por CUIT también dan ambiguo, no se elige uno', () => {
  const r = veredicto(comp({ cuitEmisor: '27123456789' }), [
    mov({ id: 1, cuitEmisor: '27123456789' }),
    mov({ id: 2, cuitEmisor: '27123456789' }),
  ])
  assert.equal(r.estado, 'ambiguo')
  assert.deepEqual([...r.candidatos].sort(), [1, 2])
})
