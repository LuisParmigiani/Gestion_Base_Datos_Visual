import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  CUENTAS, MOVIMIENTOS, COMPROBANTES, SIN_COMPROBANTE_ESPERADOS,
} from './fixtures.ts'

// Las fixtures son la vara con la que se mide F4. Si la vara está torcida, los
// tests del motor pasan igual y no significan nada. Así que se valida la vara.

const movimiento = (id: number) => MOVIMIENTOS.find((m) => m.id === id)

test('los ids de movimiento son únicos', () => {
  const ids = MOVIMIENTOS.map((m) => m.id)
  assert.equal(new Set(ids).size, ids.length)
})

test('los ids de comprobante son únicos', () => {
  const ids = COMPROBANTES.map((c) => c.id)
  assert.equal(new Set(ids).size, ids.length)
})

test('cada movimiento pertenece a una cuenta conocida', () => {
  for (const m of MOVIMIENTOS) {
    assert.ok(CUENTAS.some((c) => c.nombre === m.cuenta), `${m.cuenta} no existe`)
  }
})

test('cada movimiento esperado existe', () => {
  for (const c of COMPROBANTES) {
    if (c.movimientoEsperado === null) continue
    assert.ok(movimiento(c.movimientoEsperado),
      `el comprobante ${c.id} espera el movimiento ${c.movimientoEsperado}, que no existe`)
  }
})

test('cada candidato esperado existe', () => {
  for (const c of COMPROBANTES) {
    for (const id of c.candidatosEsperados) {
      assert.ok(movimiento(id), `el comprobante ${c.id} lista el candidato ${id}, que no existe`)
    }
  }
})

test('los seis estados están representados', () => {
  const estados = new Set(COMPROBANTES.map((c) => c.estadoEsperado))
  for (const e of ['verificado', 'sospechoso', 'no_verificable', 'duplicado', 'ambiguo']) {
    assert.ok(estados.has(e as never), `falta un caso con estado ${e}`)
  }
  assert.ok(SIN_COMPROBANTE_ESPERADOS.length > 0, 'falta el caso sin_comprobante')
})

test('las tres reglas de la cascada están cubiertas', () => {
  const reglas = new Set(COMPROBANTES.map((c) => c.reglaEsperada))
  for (const r of [1, 2, 3] as const) {
    assert.ok(reglas.has(r), `falta un caso que resuelva por regla ${r}`)
  }
})

test('un verificado trae movimiento, regla y confianza', () => {
  for (const c of COMPROBANTES.filter((x) => x.estadoEsperado === 'verificado')) {
    assert.notEqual(c.movimientoEsperado, null, `el verificado ${c.id} no dice qué movimiento`)
    assert.notEqual(c.confianzaEsperada, null, `el verificado ${c.id} no dice con qué confianza`)
    assert.notEqual(c.reglaEsperada, null, `el verificado ${c.id} no dice por qué regla`)
  }
})

test('lo que no es verificado no declara confianza ni regla', () => {
  for (const c of COMPROBANTES.filter((x) => x.estadoEsperado !== 'verificado')) {
    assert.equal(c.confianzaEsperada, null, `el comprobante ${c.id} no debería tener confianza`)
    assert.equal(c.reglaEsperada, null, `el comprobante ${c.id} no debería tener regla`)
  }
})

test('un ambiguo tiene al menos dos candidatos y ningún movimiento resuelto', () => {
  const ambiguos = COMPROBANTES.filter((c) => c.estadoEsperado === 'ambiguo')
  assert.ok(ambiguos.length > 0)
  for (const c of ambiguos) {
    assert.ok(c.candidatosEsperados.length >= 2, `el ambiguo ${c.id} tiene menos de 2 candidatos`)
    assert.equal(c.movimientoEsperado, null, `el ambiguo ${c.id} no se resuelve solo`)
  }
})

test('un duplicado comparte su movimiento con otro comprobante', () => {
  const dups = COMPROBANTES.filter((c) => c.estadoEsperado === 'duplicado')
  assert.ok(dups.length >= 2)
  for (const c of dups) {
    const otros = dups.filter((o) => o.id !== c.id && o.movimientoEsperado === c.movimientoEsperado)
    assert.ok(otros.length >= 1, `el duplicado ${c.id} no comparte movimiento con nadie`)
  }
})

test('ningún comprobante reclama un egreso', () => {
  for (const c of COMPROBANTES) {
    if (c.movimientoEsperado === null) continue
    assert.equal(movimiento(c.movimientoEsperado)?.esIngreso, true,
      `el comprobante ${c.id} reclama un egreso`)
  }
})

test('los movimientos sin comprobante son ingresos y nadie los reclama', () => {
  for (const id of SIN_COMPROBANTE_ESPERADOS) {
    const m = movimiento(id)
    assert.ok(m, `el movimiento ${id} no existe`)
    assert.equal(m?.esIngreso, true, `el movimiento ${id} es un egreso, no puede faltar comprobante`)
    const reclamado = COMPROBANTES.some(
      (c) => c.movimientoEsperado === id || c.candidatosEsperados.includes(id))
    assert.equal(reclamado, false, `el movimiento ${id} sí está reclamado`)
  }
})

test('todo ingreso o está reclamado, o es candidato, o falta su comprobante', () => {
  for (const m of MOVIMIENTOS.filter((x) => x.esIngreso)) {
    const reclamado = COMPROBANTES.some(
      (c) => c.movimientoEsperado === m.id || c.candidatosEsperados.includes(m.id))
    assert.ok(reclamado || SIN_COMPROBANTE_ESPERADOS.includes(m.id),
      `el movimiento ${m.id} quedó sin clasificar en las fixtures`)
  }
})

test('cada comprobante trae escrito qué caso es', () => {
  for (const c of COMPROBANTES) {
    assert.ok(c.caso.length > 10, `el comprobante ${c.id} no explica qué caso prueba`)
  }
})
