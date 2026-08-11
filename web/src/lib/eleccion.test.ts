import { test, before, beforeEach, after } from 'node:test'
import assert from 'node:assert/strict'
import { db } from './db.ts'
import {
  elegir, borrarEleccion, elegidas, buscarMovimientos, candidatos,
} from './eleccion.ts'

// Qué fila del extracto eligió una PERSONA cuando la cascada dejó más de un
// candidato. Es la pieza que permite medir lo único que importa mientras la
// regla se desarrolla: cuántas veces el algoritmo acierta solo.
//
// Lo que se prueba acá es que la elección no se pierda ni se pise en silencio.
// Una fila del extracto es plata que se movió una sola vez: si dos comprobantes
// la reclaman, uno de los dos está mal y hay que enterarse.

// Las tres filas del extracto con las que trabaja este archivo. Se piden a la
// base en vez de fijarles el id: los ids los da una secuencia compartida.
let mov: number[] = []

// ⚠️ Acá NO se trunca `cuenta`, `movimiento` ni `extracto_carga`. Los tests
// corren en serie sobre la misma base (`--test-concurrency=1`) y hay archivos
// posteriores que dan por sentado que las cuentas están sembradas: vaciarlas
// los deja sin piso. Este archivo crea lo suyo y se lo lleva al terminar.
before(async () => {
  const { rows: [cuenta] } = await db.query<{ id: number }>(
    "INSERT INTO cuenta (nombre, cbu) VALUES ('prueba-eleccion', NULL) RETURNING id")
  const { rows: [carga] } = await db.query<{ id: number }>(
    `INSERT INTO extracto_carga (cuenta_id, archivo, hash_archivo, filas_leidas,
       filas_nuevas, filas_duplicadas, fecha_min, fecha_max)
     VALUES ($1, 'f.xlsx', 'h-eleccion', 0, 0, 0, '2026-07-01', '2026-07-31') RETURNING id`,
    [cuenta.id])

  // Importes deliberadamente improbables: la base de test la comparten varios
  // archivos y un 100.00 chocaría con las fixtures de `conciliacion.test.ts`.
  // El CUIT va SIN guiones, que es como lo trae el extracto real: 2586 de 2586.
  const filas = [
    ['2026-07-10', '987654.32', 'TRANSFERENCIA ELECCIONTEST UNO', true, '20322951311'],
    ['2026-07-15', '123456.78', 'PAGO ELECCIONTEST DOS', true, '27111111112'],
    ['2026-07-20', '987654.32', 'TRANSFERENCIA ELECCIONTEST TRES', false, null],
  ] as const
  mov = []
  for (const [i, [fecha, importe, desc, ingreso, cuit]] of filas.entries()) {
    const { rows: [f] } = await db.query<{ id: number }>(
      `INSERT INTO movimiento (cuenta_id, carga_id, fecha, descripcion,
         importe_crudo, importe, es_ingreso, huella, hoja, fila, cuit_emisor)
       VALUES ($1, $2, $3, $4, $5::text, $5::numeric, $6, $7, 'Hoja1', $8, $9) RETURNING id`,
      [cuenta.id, carga.id, fecha, desc, importe, ingreso, `huella-eleccion-${i}`,
       10 + i, cuit])
    mov.push(f.id)
  }

  await db.query(
    `INSERT INTO corrida (nombre, descripcion, modelo)
     VALUES ('c-prueba', 'prueba', 'm') ON CONFLICT (nombre) DO NOTHING`)
})

beforeEach(async () => {
  await db.query('DELETE FROM eleccion')
  await db.query('DELETE FROM comprobante')
})

after(async () => {
  // Se lleva lo suyo: los archivos que corren después no tienen por qué
  // encontrarse con una cuenta ni tres movimientos que no sembraron.
  await db.query('DELETE FROM eleccion')
  await db.query("DELETE FROM movimiento WHERE huella LIKE 'huella-eleccion-%'")
  await db.query("DELETE FROM extracto_carga WHERE hash_archivo = 'h-eleccion'")
  await db.query("DELETE FROM cuenta WHERE nombre = 'prueba-eleccion'")
  await db.end()
})

/** Un comprobante al que le falta decidir qué fila del extracto le toca. */
async function sembrar(
  archivo: string,
  d: { monto?: string, fecha?: string, cuit?: string | null, referencia?: string | null } = {},
) {
  const { rows: [{ id }] } = await db.query<{ id: number }>(
    `INSERT INTO comprobante (archivo, hash_imagen, origen, estado_extraccion,
       corrida_base, monto, fecha, cuit_emisor, referencia)
     VALUES ($1, $1, 'ia', 'extraido', 'c-prueba', $2::numeric, $3::date, $4, $5)
     RETURNING id`,
    [archivo, d.monto ?? '100.00', d.fecha ?? '2026-07-10',
     d.cuit ?? null, d.referencia ?? null])
  return id
}

test('elegir guarda qué movimiento le corresponde al comprobante', async () => {
  const c = await sembrar('a.jpeg')
  assert.deepEqual(await elegir(c, mov[0]), { ok: true })
  assert.deepEqual([...(await elegidas())], [[c, mov[0]]])
})

test('cambiar de opinión pisa la elección anterior, no apila filas', async () => {
  const c = await sembrar('a.jpeg')
  await elegir(c, mov[0])
  assert.deepEqual(await elegir(c, mov[1]), { ok: true })
  assert.deepEqual([...(await elegidas())], [[c, mov[1]]])
})

test('un movimiento ya elegido por otro comprobante avisa en vez de romper', async () => {
  // Una fila del extracto es un movimiento de plata que ocurrió UNA vez. Si dos
  // comprobantes la reclaman hay un error en alguno de los dos, y resolverlo en
  // silencio —pisando al primero— escondería justamente lo que hay que mirar.
  const uno = await sembrar('a.jpeg')
  const otro = await sembrar('b.jpeg')
  await elegir(uno, mov[0])

  const r = await elegir(otro, mov[0])
  assert.equal(r.ok, false)
  assert.match(r.ok === false ? r.error : '', /ya está asignad/i)
  // El primero sigue intacto: el que falló no se llevó puesto nada.
  assert.deepEqual([...(await elegidas())], [[uno, mov[0]]])
})

test('volver a elegir el mismo movimiento para el mismo comprobante no es un error', async () => {
  const c = await sembrar('a.jpeg')
  await elegir(c, mov[0])
  assert.deepEqual(await elegir(c, mov[0]), { ok: true })
})

test('borrar la elección la saca y deja que el algoritmo vuelva a opinar', async () => {
  const c = await sembrar('a.jpeg')
  await elegir(c, mov[0])
  await borrarEleccion(c)
  assert.equal((await elegidas()).size, 0)
})

test('borrar el comprobante se lleva su elección: no quedan huérfanas', async () => {
  const c = await sembrar('a.jpeg')
  await elegir(c, mov[0])
  await db.query('DELETE FROM comprobante WHERE id = $1', [c])
  assert.equal((await elegidas()).size, 0)
})

test('elegidas devuelve todas, para cruzarlas contra lo que propone el algoritmo', async () => {
  const uno = await sembrar('a.jpeg')
  const otro = await sembrar('b.jpeg')
  await elegir(uno, mov[0])
  await elegir(otro, mov[1])
  assert.deepEqual([...(await elegidas())].sort(), [[uno, mov[0]], [otro, mov[1]]].sort())
})

// ─── el buscador de /encontrar/[id] ────────────────────────────────────
//
// Cuando la regla no encuentra nada, la persona tiene que poder buscar la fila
// a mano entre 2822. Lo que se prueba es que cada filtro filtre de verdad y que
// combinarlos achique: un buscador que devuelve de más es peor que ninguno,
// porque invita a dar por buena la primera fila parecida.

test('el detalle busca texto adentro de la descripción, sin distinguir mayúsculas', async () => {
  const { filas } = await buscarMovimientos({ detalle: 'elecciontest uno' })
  assert.deepEqual(filas.map((f) => f.id), [mov[0]])
})

test('el monto busca exacto: 987654.32 no trae 123456.78', async () => {
  const { filas } = await buscarMovimientos({ monto: '987654.32' })
  // El tercero es egreso y por default no entra.
  assert.deepEqual(filas.map((f) => f.id), [mov[0]])
})

test('la fecha filtra por el día exacto', async () => {
  const { filas } = await buscarMovimientos({ fecha: '2026-07-15' })
  assert.deepEqual(filas.map((f) => f.id), [mov[1]])
})

test('combinar filtros achica, no agranda', async () => {
  const solo = await buscarMovimientos({ detalle: 'ELECCIONTEST' })
  const con = await buscarMovimientos({ detalle: 'ELECCIONTEST', monto: '123456.78' })
  assert.ok(con.filas.length < solo.filas.length)
  assert.deepEqual(con.filas.map((f) => f.id), [mov[1]])
})

test('un filtro que no coincide con nada devuelve vacío, no todo', async () => {
  const { filas, total } = await buscarMovimientos({ detalle: 'NO-EXISTE-ESTE-TEXTO-XYZ' })
  assert.deepEqual(filas, [])
  assert.equal(total, 0)
})

test('el límite corta las filas pero `total` sigue diciendo cuántas hay', async () => {
  const { filas, total } = await buscarMovimientos({ detalle: 'ELECCIONTEST', limite: 1 })
  assert.equal(filas.length, 1)
  assert.equal(total, 2, 'los dos ingresos con ELECCIONTEST')
})

test('`cerca` ordena por proximidad de fecha: lo del día sale antes que lo lejano', async () => {
  // Es el default cuando la regla no encontró nada: mostrar lo que pasó cerca
  // de la fecha del comprobante es un punto de partida, no una respuesta.
  const { filas } = await buscarMovimientos({ detalle: 'ELECCIONTEST', cerca: '2026-07-15' })
  assert.equal(filas[0].id, mov[1])
})

test('el buscador trae la hoja y la fila del Excel, que es lo que se busca a mano', async () => {
  const { filas } = await buscarMovimientos({ detalle: 'ELECCIONTEST UNO' })
  assert.equal(filas[0].hoja, 'Hoja1')
  assert.equal(filas[0].fila, 10)
})

test('buscar por id trae esa fila aunque sea un egreso', async () => {
  // La fila que una persona eligió a mano hay que poder releerla siempre: si el
  // filtro de ingresos la escondiera, la pantalla se olvidaría de su decisión.
  const { filas } = await buscarMovimientos({ id: mov[2] })
  assert.deepEqual(filas.map((f) => f.id), [mov[2]])
})

test('el buscador avisa si la fila ya se la llevó otro comprobante', async () => {
  const c = await sembrar('a.jpeg')
  await elegir(c, mov[0])
  const { filas } = await buscarMovimientos({ detalle: 'ELECCIONTEST UNO' })
  assert.equal(filas[0].tomadoPor, 'a.jpeg')
})

// ─── la cascada ────────────────────────────────────────────────────────
//
// El extracto guarda el CUIT SIN guiones (2586 de 2586 filas reales) y una
// persona lo escribe en /revisar CON guiones (33 de 42). Comparar los textos
// tal cual hacía que 33 comprobantes no pudieran cruzar nunca: el cruce por
// CUIT pasaba de 40 posibles a 8 reales. Los separadores no son el dato.

test('el CUIT cruza aunque el comprobante lo tenga con guiones', async () => {
  const c = await sembrar('a.jpeg',
    { cuit: '20-32295131-1', monto: '987654.32', fecha: '2026-07-10' })
  const r = await candidatos(c)
  assert.deepEqual(r.map((x) => x.id), [mov[0]])
})

test('CUIT + monto + fecha es 90%: son tres datos independientes', async () => {
  // Antes esto caía al 50% —o a nada— porque el 90% exigía además que el nro de
  // transacción coincidiera, y en el extracto real casi nunca coincide.
  const c = await sembrar('a.jpeg',
    { cuit: '20322951311', monto: '987654.32', fecha: '2026-07-10' })
  const [r] = await candidatos(c)
  assert.equal(r.regla, '90')
})

test('sin CUIT, monto y fecha siguen valiendo 50% y no más', async () => {
  const c = await sembrar('a.jpeg', { monto: '987654.32', fecha: '2026-07-10' })
  const [r] = await candidatos(c)
  assert.equal(r.regla, '50')
})

test('ignorar los guiones NO junta dos CUIT distintos', async () => {
  // El caso del comprobante 126: 20-11260819-9 contra 20-11126081-9. La misma
  // puntuación, los mismos dígitos en otro orden — y son cuentas distintas.
  const c = await sembrar('a.jpeg',
    { cuit: '20-32295131-2', monto: '987654.32', fecha: '2026-07-10' })
  const [r] = await candidatos(c)
  assert.equal(r.regla, '50', 'el CUIT no coincide: no puede subir a 90%')
})

test('el CUIT desempata cuando monto y fecha dejan dos candidatos', async () => {
  // Es el caso que reportó el usuario en los comprobantes 23 y 30: dos filas del
  // mismo importe y la misma fecha, pero solo una con su CUIT.
  const { rows: [extra] } = await db.query<{ id: number }>(
    `INSERT INTO movimiento (cuenta_id, carga_id, fecha, descripcion, importe_crudo,
       importe, es_ingreso, huella, hoja, fila, cuit_emisor)
     SELECT cuenta_id, carga_id, '2026-07-10', 'GEMELO ELECCIONTEST', '987654.32',
            987654.32, true, 'huella-eleccion-gemelo', 'Hoja1', 99, '30999999998'
     FROM movimiento WHERE id = $1 RETURNING id`, [mov[0]])
  try {
    const sinCuit = await sembrar('a.jpeg', { monto: '987654.32', fecha: '2026-07-10' })
    assert.equal((await candidatos(sinCuit)).length, 2, 'sin CUIT quedan los dos')

    const conCuit = await sembrar('b.jpeg',
      { cuit: '20-32295131-1', monto: '987654.32', fecha: '2026-07-10' })
    const r = await candidatos(conCuit)
    assert.deepEqual(r.map((x) => x.id), [mov[0]], 'con CUIT queda uno solo')
    assert.equal(r[0].regla, '90')
  } finally {
    await db.query('DELETE FROM movimiento WHERE id = $1', [extra.id])
  }
})
