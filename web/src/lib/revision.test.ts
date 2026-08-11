import { test, before, after, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { db } from './db.ts'
import {
  guardarRevision, proximoPendiente, cargarComprobante,
  motivosDeFormato, aceptarFormato, proximo,
} from './revision.ts'

// La corrección humana es lo que produce la verdad de referencia del proyecto:
// sin ella no se puede medir un solo acierto del modelo. Lo que se prueba acá
// es que esa corrección no se pierde nunca en silencio.
//
// Un campo que llenó la IA puede vaciarse sin drama: el crudo sobrevive en
// `extraccion.campos` y /revisar lo muestra al lado. Un campo que llenó una
// persona, no: si no se puede guardar, hay que avisar, no tragarlo.

/** Un comprobante listo para revisar. Devuelve su id. */
async function sembrar(archivo: string, base = 'c-prueba') {
  const { rows: [{ id }] } = await db.query<{ id: number }>(
    `INSERT INTO comprobante (archivo, hash_imagen, origen, estado_extraccion, corrida_base,
                              monto, fecha, nombre_emisor)
     VALUES ($1, $1, 'ia', 'extraido', $2, 100.00, '2026-07-01', 'ORIGINAL')
     RETURNING id`, [archivo, base])
  return id
}

async function leer(id: number) {
  const { rows: [f] } = await db.query(
    `SELECT monto::text, to_char(fecha,'YYYY-MM-DD') AS fecha, to_char(hora,'HH24:MI') AS hora,
            nombre_emisor, coelsa_id, estado_extraccion,
            (revisado_en IS NOT NULL) AS revisado
     FROM comprobante WHERE id = $1`, [id])
  return f
}

/** Los 16 campos como los manda el formulario: todo texto. */
const formulario = (cambios: Record<string, string> = {}) => ({
  tipo_operacion: 'transferencia', monto: '4800', moneda: 'ARS',
  fecha: '27/06/2026', hora: '19:16', nombre_emisor: 'GOMEZ, ANA',
  cuit_emisor: '27123456789', cbu_cvu_emisor: '', banco_emisor: 'BANCO MACRO',
  nombre_receptor: 'PEREZ SRL', cuit_receptor: '30555666777', cbu_cvu_receptor: '',
  banco_receptor: '', concepto: '', referencia: '', coelsa_id: '',
  ...cambios,
})

before(async () => {
  await db.query('TRUNCATE comprobante, corrida RESTART IDENTITY CASCADE')
  await db.query(
    `INSERT INTO corrida (nombre, descripcion, modelo)
     VALUES ('c-prueba', 'prueba', 'modelo-de-prueba'), ('sintetico', 'prueba', 'ninguno')`)
})

beforeEach(async () => {
  await db.query('DELETE FROM comprobante')
})

after(async () => { await db.end() })

// ─── el chequeo de forma: lógica pura, no toca la base ─────────────────
//
// No detecta errores, detecta formas IMPOSIBLES. Un CUIT tiene 11 dígitos y un
// CBU/CVU tiene 22: si la verdad guarda otra cosa, o la imagen mostraba el
// número cortado, o se perdió un dígito al corregir. Los dos casos quieren que
// una persona lo mire, que es todo lo que esto pide.

test('un CUIT de 11 dígitos y un CBU de 22 no tienen nada que revisar', () => {
  assert.deepEqual(motivosDeFormato(formulario()), [])
})

test('los separadores no cuentan: 20-11126081-9 son 11 dígitos', () => {
  assert.deepEqual(motivosDeFormato(formulario({ cuit_emisor: '20-11126081-9' })), [])
})

test('un CUIT al que le falta un dígito se marca', () => {
  // El caso real: `20-1126081-9` aparece en 4 de los 51 revisados a mano.
  assert.deepEqual(
    motivosDeFormato(formulario({ cuit_receptor: '20-1126081-9' })),
    ['CUIT del receptor: 10 dígitos, se esperan 11'])
})

test('un CBU que no da 22 dígitos se marca', () => {
  assert.deepEqual(
    motivosDeFormato(formulario({ cbu_cvu_emisor: '00000003100015126164062' })),
    ['CBU/CVU del emisor: 23 dígitos, se esperan 22'])
})

test('un CBU metido en el campo del CUIT se marca: es un campo en el lugar equivocado', () => {
  // Caso real, comprobante 117. Es el error que más importa: no es un dígito
  // mal leído, es el dato correcto en la casilla equivocada.
  assert.deepEqual(
    motivosDeFormato(formulario({ cuit_receptor: '2850795040094731285108' })),
    ['CUIT del receptor: 22 dígitos, se esperan 11'])
})

test('el texto "null" guardado como valor se marca', () => {
  // El modelo devuelve `null`, `N/A` y `none` como texto. `oNulo` atrapa dos de
  // las tres, así que la palabra puede terminar guardada como si fuera un dato.
  assert.deepEqual(motivosDeFormato(formulario({ concepto: 'null' })),
    ['Concepto: dice "null", que no es un valor'])
  assert.deepEqual(motivosDeFormato(formulario({ nombre_receptor: 'N/A' })),
    ['Nombre del receptor: dice "N/A", que no es un valor'])
})

test('un campo vacío NO se marca: vacío es una respuesta válida', () => {
  // "No figura en el comprobante" es información, no un error.
  assert.deepEqual(motivosDeFormato(formulario({ cuit_emisor: '', cbu_cvu_emisor: '' })), [])
})

test('se listan TODOS los motivos, no solo el primero', () => {
  // Es el bug que reportó el usuario: arregló el CBU, guardó, y el comprobante
  // seguía marcado porque el CUIT también estaba mal y nadie se lo dijo.
  // En el orden de los 16 campos, que es el mismo en que se ven en pantalla.
  assert.deepEqual(
    motivosDeFormato(formulario({ cuit_receptor: '20-1126081-9', cbu_cvu_emisor: '123' })),
    ['CBU/CVU del emisor: 3 dígitos, se esperan 22',
      'CUIT del receptor: 10 dígitos, se esperan 11'])
})

test('aceptar el formato saca al comprobante de la lista de dudas', async () => {
  const id = await sembrar('duda.jpeg')
  await guardarRevision(id, formulario({ cuit_receptor: '20-1126081-9' }))
  const antes = await db.query('SELECT formato_aceptado_en FROM comprobante WHERE id=$1', [id])
  assert.equal(antes.rows[0].formato_aceptado_en, null, 'guardar no acepta el formato solo')

  await aceptarFormato(id)
  const despues = await db.query('SELECT formato_aceptado_en FROM comprobante WHERE id=$1', [id])
  assert.ok(despues.rows[0].formato_aceptado_en, 'el botón "Guardar igual" tiene que dejar marca')
})

test('guardar SIEMPRE lleva al siguiente si queda alguno, aunque el filtro esté vacío', async () => {
  // El bug reportado: con los 51 ya revisados, "pendientes" está vacío. Si la
  // URL no traía `?filtro=`, `proximo` buscaba en esa cola vacía, devolvía null
  // y la pantalla se iba a la lista en vez de al comprobante siguiente.
  const a = await sembrar('a.jpeg')
  const b = await sembrar('b.jpeg')
  await guardarRevision(a, formulario())
  await guardarRevision(b, formulario())

  assert.equal(await proximo('pendientes', a), b,
    'no queda ningún pendiente, pero todavía hay comprobantes que revisar')
})

test('el orden no se mueve al guardar: el siguiente es el siguiente', async () => {
  // Ordenar por `revisado_en` hacía que guardar mandara el comprobante al final
  // de la cola, y entonces "el que sigue" pasaba a ser otro. El recorrido tiene
  // que depender del id, que no cambia.
  const a = await sembrar('a.jpeg')
  const b = await sembrar('b.jpeg')
  const c = await sembrar('c.jpeg')
  await guardarRevision(b, formulario())   // el del medio, y primero

  assert.equal(await proximo('todos', a), b)
  assert.equal(await proximo('todos', b), c)
  assert.equal(await proximo('todos', c), null, 'el último cierra el recorrido')
})

test('si el comprobante salió del filtro, sigue por el próximo y no vuelve al principio', async () => {
  const a = await sembrar('a.jpeg')
  const b = await sembrar('b.jpeg')
  const c = await sembrar('c.jpeg')
  // Los tres con un CUIT corto: los tres quedan en "dudas".
  for (const id of [a, b, c]) await guardarRevision(id, formulario({ cuit_receptor: '20-1126081-9' }))
  // Se arregla el del medio: sale de la cola.
  await guardarRevision(b, formulario())

  assert.equal(await proximo('dudas', b), c, 'tiene que seguir hacia adelante, no volver a `a`')
})

test('corregir de verdad el campo tampoco necesita aceptar nada', async () => {
  const id = await sembrar('arreglado.jpeg')
  const r = await guardarRevision(id, formulario({ cuit_receptor: '20-11126081-9' }))
  assert.ok(r.ok)
  assert.deepEqual(r.motivos, [], 'sin motivos, la pantalla salta al siguiente')
})

// ─── lo que se guarda ──────────────────────────────────────────────────

test('la corrección queda escrita y el comprobante marcado como revisado', async () => {
  const id = await sembrar('uno.jpeg')
  const r = await guardarRevision(id, formulario({ nombre_emisor: 'GOMEZ, ANA MARIA' }))

  assert.equal(r.ok, true)
  const c = await leer(id)
  assert.equal(c.nombre_emisor, 'GOMEZ, ANA MARIA')
  assert.equal(c.revisado, true)
  assert.equal(c.estado_extraccion, 'confirmado')
})

test('un monto con formato argentino se guarda como número, no rompe', async () => {
  // El caso que hoy tira un 500 y pierde la revisión entera.
  const id = await sembrar('dos.jpeg')
  const r = await guardarRevision(id, formulario({ monto: '$ 81.687,80' }))

  assert.equal(r.ok, true)
  assert.equal((await leer(id)).monto, '81687.80')
})

test('un campo vacío es ausencia válida y se guarda en NULL', async () => {
  const id = await sembrar('tres.jpeg')
  const r = await guardarRevision(id, formulario({ coelsa_id: '   ' }))

  assert.equal(r.ok, true)
  assert.equal((await leer(id)).coelsa_id, null)
})

// ─── lo que NO se guarda, y se avisa ───────────────────────────────────

test('un monto ambiguo no se guarda: se avisa cuál es', async () => {
  const id = await sembrar('cuatro.jpeg')
  const r = await guardarRevision(id, formulario({ monto: '$ 1.500' }))

  assert.equal(r.ok, false)
  assert.deepEqual(r.ok === false && r.invalidos, ['monto'])
})

test('una fecha que no existe no se guarda: se avisa', async () => {
  const id = await sembrar('cinco.jpeg')
  const r = await guardarRevision(id, formulario({ fecha: '30/02/2026' }))

  assert.equal(r.ok, false)
  assert.deepEqual(r.ok === false && r.invalidos, ['fecha'])
})

test('se avisan TODOS los campos inválidos, no solo el primero', async () => {
  const id = await sembrar('seis.jpeg')
  const r = await guardarRevision(id, formulario({ monto: '$ 1.500', hora: '99:99' }))

  assert.deepEqual(r.ok === false && r.invalidos, ['monto', 'hora'])
})

test('si hay un campo inválido no se escribe NADA: ni los que sí valían', async () => {
  // Lo peor sería guardar 15 campos y perder uno sin decirlo: la persona se va
  // creyendo que revisó el comprobante entero.
  const id = await sembrar('siete.jpeg')
  const r = await guardarRevision(id, formulario({ monto: '$ 1.500', nombre_emisor: 'NUEVO' }))

  assert.equal(r.ok, false)
  const c = await leer(id)
  assert.equal(c.nombre_emisor, 'ORIGINAL', 'se escribió una corrección parcial')
  assert.equal(c.monto, '100.00')
  assert.equal(c.revisado, false, 'quedó marcado como revisado sin haberse guardado')
})

// ─── el próximo pendiente ──────────────────────────────────────────────

test('al guardar salta al próximo comprobante sin revisar', async () => {
  const a = await sembrar('a.jpeg')
  const b = await sembrar('b.jpeg')
  const r = await guardarRevision(a, formulario())

  assert.equal(r.ok === true && r.siguiente, b)
})

test('los sintéticos no entran en la cola de revisión', async () => {
  const a = await sembrar('a.jpeg')
  await sembrar('sint.jpeg', 'sintetico')
  const r = await guardarRevision(a, formulario())

  assert.equal(r.ok === true && r.siguiente, null, 'un sintético no es verdad de referencia')
})

test('cuando no queda ninguno pendiente, no hay próximo', async () => {
  const a = await sembrar('a.jpeg')
  const r = await guardarRevision(a, formulario())

  assert.equal(r.ok === true && r.siguiente, null)
})

test('el próximo da la vuelta si el que se revisó era el último', async () => {
  const a = await sembrar('a.jpeg')
  const b = await sembrar('b.jpeg')
  await guardarRevision(b, formulario())

  assert.equal(await proximoPendiente(b), a, 'quedó uno pendiente antes y no se ofreció')
})

// ═══ La carga a mano ═══════════════════════════════════════════════════
//
// El otro camino por el que una persona escribe un comprobante: sin IA de por
// medio. Mismo criterio que la revisión — lo que no se puede convertir no se
// guarda a medias ni se adivina.

test('un comprobante cargado a mano queda confirmado y con origen manual', async () => {
  const r = await cargarComprobante('hash-1', 'a mano.jpeg', formulario())

  assert.equal(r.ok, true)
  const { rows: [c] } = await db.query(
    `SELECT origen, estado_extraccion, monto::text FROM comprobante WHERE hash_imagen = 'hash-1'`)
  assert.equal(c.origen, 'manual')
  assert.equal(c.estado_extraccion, 'confirmado')
  assert.equal(c.monto, '4800.00')
})

test('un monto con formato argentino se carga bien, no rompe', async () => {
  const r = await cargarComprobante('hash-2', 'b.jpeg', formulario({ monto: '$ 81.687,80' }))

  assert.equal(r.ok, true)
  const { rows: [c] } = await db.query(
    `SELECT monto::text FROM comprobante WHERE hash_imagen = 'hash-2'`)
  assert.equal(c.monto, '81687.80')
})

test('un monto ambiguo no se carga: se avisa y no queda nada escrito', async () => {
  const r = await cargarComprobante('hash-3', 'c.jpeg', formulario({ monto: '$ 1.500' }))

  assert.equal(r.ok, false)
  assert.deepEqual(r.ok === false && r.invalidos, ['monto'])
  const { rows } = await db.query(`SELECT 1 FROM comprobante WHERE hash_imagen = 'hash-3'`)
  assert.equal(rows.length, 0, 'se insertó un comprobante que no se pudo interpretar')
})

test('sin monto o sin fecha no se puede cruzar: no se carga', async () => {
  for (const falta of ['monto', 'fecha']) {
    const r = await cargarComprobante(`hash-f-${falta}`, 'd.jpeg', formulario({ [falta]: '' }))
    assert.equal(r.ok, false, `${falta} vacío debería impedir la carga`)
    assert.match(r.ok === false ? r.error : '', /monto|fecha/i)
  }
})

test('la misma imagen cargada dos veces se detecta y no se duplica', async () => {
  await cargarComprobante('hash-4', 'e.jpeg', formulario())
  const otra = await cargarComprobante('hash-4', 'otro-nombre.jpeg', formulario())

  assert.equal(otra.ok, false)
  assert.match(otra.ok === false ? otra.error : '', /ya se cargó/i)
  const { rows } = await db.query(
    `SELECT count(*)::int AS n FROM comprobante WHERE hash_imagen = 'hash-4'`)
  assert.equal(rows[0].n, 1)
})
