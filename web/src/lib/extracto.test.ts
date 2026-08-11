import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  parsearImporte, fechaDeCelda, extraerCuit, extraerCoelsa, extraerTipo, huella,
} from './extracto.ts'

// El extracto trae dos formatos de número mezclados en la misma columna.
// Un parser ingenuo lee 368.500,00 como 368,50 y no rompe nada: solo produce
// un número equivocado que después acusa a un cliente honesto.

test('formato argentino: el último separador es el decimal', () => {
  assert.deepEqual(parsearImporte('$ 368.500,00'),
    { importe: '368500.00', esIngreso: true, ambiguo: false })
})

test('formato estadounidense: el último separador es el decimal', () => {
  assert.deepEqual(parsearImporte('$ 16,000.00'),
    { importe: '16000.00', esIngreso: true, ambiguo: false })
})

test('un importe negativo es un egreso', () => {
  assert.deepEqual(parsearImporte('-$ 112,340.06'),
    { importe: '-112340.06', esIngreso: false, ambiguo: false })
})

test('varios separadores de miles y una coma decimal', () => {
  assert.deepEqual(parsearImporte('$ 5.094.237,85'),
    { importe: '5094237.85', esIngreso: true, ambiguo: false })
})

test('sin separadores', () => {
  assert.deepEqual(parsearImporte('$ 250000'),
    { importe: '250000', esIngreso: true, ambiguo: false })
})

// Un solo separador: la cantidad de dígitos que le siguen decide.

test('un separador con dos dígitos detrás es un decimal', () => {
  assert.deepEqual(parsearImporte('$ 1.50'),
    { importe: '1.50', esIngreso: true, ambiguo: false })
  assert.deepEqual(parsearImporte('$ 1,50'),
    { importe: '1.50', esIngreso: true, ambiguo: false })
})

test('un separador con un dígito detrás es un decimal', () => {
  assert.deepEqual(parsearImporte('$ 1,5'),
    { importe: '1.5', esIngreso: true, ambiguo: false })
})

test('un separador con tres dígitos detrás es AMBIGUO y no se adivina', () => {
  assert.deepEqual(parsearImporte('$ 1.500'),
    { importe: null, esIngreso: true, ambiguo: true })
  assert.deepEqual(parsearImporte('$ 1,500'),
    { importe: null, esIngreso: true, ambiguo: true })
})

test('un ambiguo negativo conserva el signo aunque no tenga importe', () => {
  assert.deepEqual(parsearImporte('-$ 1.500'),
    { importe: null, esIngreso: false, ambiguo: true })
})

// Dos separadores iguales no pueden ser decimales: un número tiene un solo
// punto decimal. '1.234.567' es un millón y pico, sin ambigüedad posible.
test('dos separadores del mismo tipo son miles, no ambigüedad', () => {
  assert.deepEqual(parsearImporte('$ 1.234.567'),
    { importe: '1234567', esIngreso: true, ambiguo: false })
})

test('una celda sin dígitos no se inventa: queda ambigua', () => {
  assert.deepEqual(parsearImporte(''),
    { importe: null, esIngreso: true, ambiguo: true })
})

// Nunca un float: el importe vuelve como string y se lo come NUMERIC.
// 0.1 + 0.2 !== 0.3 y esto es plata.
test('el importe vuelve como string, nunca como number', () => {
  assert.equal(typeof parsearImporte('$ 368.500,00').importe, 'string')
})

// ─── Fechas ────────────────────────────────────────────────────────────
// Verificado contra el archivo real: `exceljs` devuelve las 2843 celdas como
// Date, todas a medianoche UTC. El serial queda cubierto igual porque el
// archivo es un pegado manual de descargas y una podría venir cruda.

test('una celda Date se convierte a fecha ISO', () => {
  assert.equal(fechaDeCelda(new Date(Date.UTC(2026, 1, 27))), '2026-02-27')
})

test('la fecha se lee en UTC, sin correrse por el huso horario', () => {
  assert.equal(fechaDeCelda(new Date(Date.UTC(2026, 1, 27, 23, 59))), '2026-02-27')
})

test('un serial de Excel se convierte a fecha', () => {
  assert.equal(fechaDeCelda(46080), '2026-02-27')
})

test('el serial con parte decimal ignora la hora', () => {
  assert.equal(fechaDeCelda(46080.75), '2026-02-27')
})

test('un serial fuera de rango no se convierte', () => {
  assert.equal(fechaDeCelda(0), null)
  assert.equal(fechaDeCelda(Number.NaN), null)
})

test('una celda vacía o de otro tipo no inventa una fecha', () => {
  assert.equal(fechaDeCelda(null), null)
  assert.equal(fechaDeCelda(undefined), null)
  assert.equal(fechaDeCelda(''), null)
  assert.equal(fechaDeCelda('27/02/2026'), null)
})

test('una Date inválida no se convierte', () => {
  assert.equal(fechaDeCelda(new Date('nada')), null)
})

// ─── CUIT ──────────────────────────────────────────────────────────────
// Embebido en la descripción. Es la clave de cruce principal de F4.

test('extrae el CUIT de la descripción', () => {
  assert.equal(extraerCuit('ING TRANSF 27123456789 GOMEZ/A'), '27123456789')
})

test('acepta los prefijos válidos de CUIT', () => {
  for (const p of ['20', '23', '24', '27', '30', '33', '34']) {
    assert.equal(extraerCuit(`TRANSF ${p}123456789 X`), `${p}123456789`)
  }
})

test('no confunde un prefijo inválido con un CUIT', () => {
  assert.equal(extraerCuit('TRANSF 99123456789 X'), null)
})

test('no recorta un CUIT de adentro de un número más largo', () => {
  assert.equal(extraerCuit('TRANSF 9027123456789012 X'), null)
})

test('sin CUIT devuelve null, no string vacío', () => {
  assert.equal(extraerCuit('MOVISTAR FACTURA'), null)
})

// ─── ID COELSA ─────────────────────────────────────────────────────────
// Solo el ~3% de las filas lo trae, pero cuando está es certeza total.

test('extrae el COELSA después de TRANSF:', () => {
  assert.equal(extraerCoelsa('TRANSF:ABC123DEF456GHI789JKL0-20123456789'),
    'ABC123DEF456GHI789JKL0')
})

test('extrae el COELSA después de CREDIN:', () => {
  assert.equal(extraerCoelsa('CREDIN:ABC123DEF456GHI789JKL0'),
    'ABC123DEF456GHI789JKL0')
})

test('sin COELSA devuelve null', () => {
  assert.equal(extraerCoelsa('ING TRANSF 27123456789 GOMEZ/A'), null)
})

test('un token demasiado corto no es un COELSA', () => {
  assert.equal(extraerCoelsa('TRANSF:ABC123'), null)
})

// ─── Tipo ──────────────────────────────────────────────────────────────

test('reconoce el tipo por el prefijo de la descripción', () => {
  assert.equal(extraerTipo('TEF 27123456789 X'), 'TEF')
  assert.equal(extraerTipo('MOVISTAR FACTURA'), 'MOVISTAR')
})

test('ING TRANSF gana sobre TRANSF, que es su prefijo', () => {
  assert.equal(extraerTipo('ING TRANSF 27123456789 X'), 'ING TRANSF')
})

test('una descripción sin prefijo conocido no inventa un tipo', () => {
  assert.equal(extraerTipo('ALGO QUE NO ESTA EN LA LISTA'), null)
})

// ─── Huella ────────────────────────────────────────────────────────────
// Es el UNIQUE que deduplica. Usa importe_crudo y no el importe parseado:
// las filas ambiguas tienen importe NULL y colisionarían todas entre sí.

const fila = {
  cuenta: 'SUCESION', fecha: '2026-02-27', nro: '123456',
  importeCrudo: '$ 368.500,00', descripcion: 'ING TRANSF 27123456789 X',
}

test('la misma fila da siempre la misma huella', () => {
  assert.equal(huella(fila), huella({ ...fila }))
})

test('cambiar cualquier campo cambia la huella', () => {
  for (const campo of Object.keys(fila) as (keyof typeof fila)[]) {
    assert.notEqual(huella({ ...fila, [campo]: 'otro' }), huella(fila),
      `cambiar ${campo} no cambió la huella`)
  }
})

test('dos filas ambiguas distintas no colisionan', () => {
  assert.notEqual(
    huella({ ...fila, importeCrudo: '$ 1.500' }),
    huella({ ...fila, importeCrudo: '$ 2.500' }))
})
