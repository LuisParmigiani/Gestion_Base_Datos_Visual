import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { db } from './db.ts'
import { CAMPOS, normalizarCampo, paraColumna, importarComprobantes } from './importar-comprobantes.ts'

// `normalizarCampo` decide qué cuenta como ACIERTO del modelo. De ella salen los
// porcentajes de /corridas, que son los números del informe. Un error acá no se
// ve: produce un modelo que "falla" campos que sacó bien, o al revés.
//
// Ya mordió una vez —se comparaba el crudo del modelo contra la columna ya
// convertida y `monto`, `fecha` y `hora` figuraban corregidos sin que nadie los
// tocara—, y por eso la usan los tres lugares que comparan. Estos tests fijan el
// contrato para que los tres sigan viendo lo mismo.
//
// Lógica pura: no toca la base ni el disco. Los datos son inventados, nunca
// reales.

/** Los dos lados que compara /corridas: el crudo del modelo y la columna. */
const mismoValor = (campo: Parameters<typeof normalizarCampo>[0], ia: unknown, columna: unknown) =>
  normalizarCampo(campo, ia) === normalizarCampo(campo, columna)

// ─── monto ─────────────────────────────────────────────────────────────

test('el monto con formato argentino es el mismo valor que la columna NUMERIC', () => {
  assert.ok(mismoValor('monto', '$ 81.687,80', '81687.80'),
    'el modelo escribe $ 81.687,80 y la columna guarda 81687.80: es el mismo importe')
})

test('el monto sin decimales es el mismo valor que la columna con dos', () => {
  assert.ok(mismoValor('monto', '250000', '250000.00'),
    'NUMERIC(14,2) siempre devuelve dos decimales: no puede contar como corrección')
})

test('el formato estadounidense también coincide con la columna', () => {
  assert.ok(mismoValor('monto', '$ 16,000.00', '16000.00'))
})

test('un monto ambiguo no se adivina: queda vacío', () => {
  // $ 1.500 puede ser mil quinientos o uno con cincuenta. Adivinar es lo que el
  // proyecto prohíbe, y acá el error sería silencioso.
  assert.equal(normalizarCampo('monto', '$ 1.500'), '')
})

test('un monto ambiguo nunca cuenta como acierto contra un valor real', () => {
  assert.ok(!mismoValor('monto', '$ 1.500', '1500.00'),
    'si se adivinara, un importe irresoluble contaría como bien extraído')
})

test('un CBU leído como monto queda vacío, nunca truncado', () => {
  // El modelo a veces devuelve el CBU de 22 dígitos en el campo monto.
  // NUMERIC(14,2) admite 12 enteros: truncarlo sería inventar un importe.
  assert.equal(normalizarCampo('monto', '0070599520000012345678'), '')
})

test('dos montos distintos no se confunden', () => {
  assert.ok(!mismoValor('monto', '4800', '4.800,50'))
})

// ─── fecha y hora ──────────────────────────────────────────────────────

test('la fecha del comprobante es la misma que la de la columna DATE', () => {
  assert.ok(mismoValor('fecha', '27/06/2026', '2026-06-27'))
})

test('la fecha con guiones también coincide', () => {
  assert.ok(mismoValor('fecha', '27-06-2026', '2026-06-27'))
})

test('la hora con texto alrededor es la misma que la columna TIME', () => {
  assert.ok(mismoValor('hora', '19:16 hs', '19:16:00'),
    'el modelo escribe 19:16 hs y la columna guarda 19:16:00')
})

test('dos fechas distintas no se confunden', () => {
  assert.ok(!mismoValor('fecha', '27/06/2026', '2026-06-28'))
})

// ─── ausencia ──────────────────────────────────────────────────────────

test('N/A es ausencia, no un valor: coincide con la columna en NULL', () => {
  // 11 de los 51 comprobantes reales no tienen COELSA. Ahí `null` es la
  // respuesta correcta y el modelo acertó.
  assert.ok(mismoValor('coelsa_id', 'N/A', null))
})

test('el vacío y los espacios también son ausencia', () => {
  for (const nada of ['', '   ', null, undefined]) {
    assert.equal(normalizarCampo('coelsa_id', nada), '', `${JSON.stringify(nada)} debería ser vacío`)
  }
})

test('un campo inventado no cuenta como acierto contra una columna vacía', () => {
  // El modo de falla dominante: inventar campos del emisor. cbu_cvu_emisor
  // inventado en 24 de 51. Tiene que contar como error.
  assert.ok(!mismoValor('cbu_cvu_emisor', '0070599520000012345678', null))
})

// ─── los 13 campos de texto ────────────────────────────────────────────

test('un campo de texto se compara sin espacios de sobra y en minúsculas', () => {
  assert.equal(normalizarCampo('nombre_emisor', '  GOMEZ, ANA  '), 'gomez, ana')
  // Los espacios de ADENTRO no se tocan: se midió sobre las 6 corridas y no
  // explican un solo fallo, así que colapsarlos sería código sin cliente.
  assert.equal(normalizarCampo('nombre_emisor', 'GOMEZ,  ANA'), 'gomez,  ana')
})

test('las mayúsculas NO distinguen: la variedad de tipeo no cuenta como error', () => {
  // Este test decía lo contrario hasta el 2026-08-11 y existía como alarma:
  // "si algún día se decide plegar mayúsculas, que sea a propósito". Se decidió.
  // Motivo, medido sobre los 16 apartados: la mayúscula generaba 14 falsos
  // errores en `lora_v3_final` contra 3 en el base, o sea ~4 puntos de castigo
  // al LoRA por tipeo. Lo que se mide es si el dato está bien y en el campo que
  // corresponde. Los espacios NO se pliegan: se midió y no aportan un solo caso.
  assert.ok(mismoValor('banco_emisor', 'Mercado Pago', 'MERCADO PAGO'))
  assert.ok(mismoValor('concepto', 'varios', 'Varios'))
  assert.ok(mismoValor('nombre_receptor', 'Rojas Alberto Enrique', 'ROJAS ALBERTO ENRIQUE'))
})

test('plegar mayúsculas no borra la diferencia entre dos valores distintos', () => {
  assert.ok(!mismoValor('banco_emisor', 'Banco Macro', 'Banco Nación'))
  assert.ok(!mismoValor('cbu_cvu_receptor', '0170099220000012345678', '0170099220000012345679'))
})

test('lo que se GUARDA conserva las mayúsculas que tipeó la persona', () => {
  // El plegado vive en `normalizarCampo` (comparación) y no en `paraColumna`
  // (lo que va a la base). Moverlo reescribiría la verdad de referencia, que es
  // lo más caro que tiene el proyecto: 51 comprobantes corregidos a mano.
  assert.equal(paraColumna('banco_emisor', 'Mercado Pago').valor, 'Mercado Pago')
  assert.equal(paraColumna('nombre_emisor', 'GOMEZ, ANA').valor, 'GOMEZ, ANA')
})

test('los 16 campos están, y una sola vez', () => {
  assert.equal(CAMPOS.length, 16)
  assert.equal(new Set(CAMPOS).size, 16)
})

// ═══ El importador, contra conciliador_test ════════════════════════════
//
// Lo que sostiene toda la medición: la misma imagen en dos corridas tiene que
// ser UN comprobante con DOS extracciones. Si fueran dos comprobantes, comparar
// corridas no significaría nada. Y `extraccion.campos` —lo que contestó el
// modelo— no se pisa nunca: es la única evidencia contra la que se mide.
//
// Las "imágenes" son bytes inventados: el importador solo las usa para sacar el
// hash que identifica al comprobante. Nunca un comprobante real en un test.

let dir: string

/** Una imagen falsa, con contenido propio para que su hash sea distinto. */
async function imagen(nombre: string) {
  await writeFile(join(dir, nombre), `bytes de ${nombre}`)
  return nombre
}

/** Un JSONL en la forma que produce `ia/extraer.py`. */
async function jsonl(nombre: string, filas: { archivo: string, campos: object }[]) {
  const ruta = join(dir, nombre)
  await writeFile(ruta, filas.map((f) => JSON.stringify(f)).join('\n'))
  return ruta
}

const corrida = (nombre: string) => ({
  nombre, descripcion: `prueba ${nombre}`, modelo: 'modelo-de-prueba',
})

/** Las columnas tipadas de un comprobante, como texto comparable. */
async function comprobante(archivo: string) {
  const { rows } = await db.query(
    `SELECT id, monto::text, to_char(fecha,'YYYY-MM-DD') AS fecha,
            to_char(hora,'HH24:MI') AS hora, cuit_emisor, coelsa_id, corrida_base
     FROM comprobante WHERE archivo = $1`, [archivo])
  return rows[0]
}

before(async () => {
  await db.query('TRUNCATE comprobante, corrida RESTART IDENTITY CASCADE')
  dir = await mkdtemp(join(tmpdir(), 'comprobantes-prueba-'))
})

after(async () => {
  await rm(dir, { recursive: true, force: true })
  await db.end()
})

test('la misma imagen en dos corridas es UN comprobante con DOS extracciones', async () => {
  const a = await imagen('uno.jpeg')
  const campos = { monto: '$ 4.800,00', fecha: '27/06/2026', cuit_emisor: '27123456789' }

  await importarComprobantes(
    await jsonl('c1.jsonl', [{ archivo: a, campos }]), corrida('c1'), { imagenes: dir })
  const segunda = await importarComprobantes(
    await jsonl('c2.jsonl', [{ archivo: a, campos: { ...campos, monto: '$ 9.999,00' } }]),
    corrida('c2'), { imagenes: dir })

  assert.equal(segunda.comprobantesNuevos, 0, 'la misma imagen no puede crear otro comprobante')
  const { rows: [{ comprobantes, extracciones }] } = await db.query<
    { comprobantes: number, extracciones: number }>(
    `SELECT (SELECT count(*)::int FROM comprobante) AS comprobantes,
            (SELECT count(*)::int FROM extraccion)  AS extracciones`)
  assert.equal(comprobantes, 1)
  assert.equal(extracciones, 2, 'sin las dos extracciones no hay nada que comparar')
})

test('lo que contestó el modelo se guarda crudo, sin normalizar', async () => {
  // Si se guardara ya convertido, se perdería la evidencia de CÓMO lo escribió
  // el modelo, que es justo lo que se está midiendo.
  const { rows: [{ campos }] } = await db.query<{ campos: { monto: string } }>(
    `SELECT campos FROM extraccion WHERE corrida = 'c1'`)
  assert.equal(campos.monto, '$ 4.800,00')
})

test('una corrida base siembra las columnas tipadas ya convertidas', async () => {
  const b = await imagen('dos.jpeg')
  await importarComprobantes(
    await jsonl('base.jsonl', [{
      archivo: b,
      campos: { monto: '$ 81.687,80', fecha: '27/06/2026', hora: '19:16 hs', coelsa_id: 'N/A' },
    }]),
    corrida('base'), { imagenes: dir, base: true })

  const c = await comprobante('dos.jpeg')
  assert.equal(c.monto, '81687.80')
  assert.equal(c.fecha, '2026-06-27')
  assert.equal(c.hora, '19:16')
  assert.equal(c.coelsa_id, null, 'N/A es ausencia: no puede guardarse como si fuera un ID')
  assert.equal(c.corrida_base, 'base')
})

test('un monto ambiguo va a NULL en la columna, pero el crudo sobrevive', async () => {
  const c = await imagen('tres.jpeg')
  await importarComprobantes(
    await jsonl('amb.jsonl', [{ archivo: c, campos: { monto: '$ 1.500', fecha: '01/07/2026' } }]),
    corrida('amb'), { imagenes: dir, base: true })

  assert.equal((await comprobante('tres.jpeg')).monto, null, 'un importe ambiguo se adivinó')
  const { rows: [{ campos }] } = await db.query<{ campos: { monto: string } }>(
    `SELECT campos FROM extraccion WHERE corrida = 'amb'`)
  assert.equal(campos.monto, '$ 1.500', 'el valor crudo tiene que poder recuperarse')
})

test('una corrida base NO pisa la corrección de una persona', async () => {
  // Es la regla que protege lo más valioso del proyecto: las 51 revisiones
  // humanas. Reimportar una corrida no puede borrarlas.
  const d = await imagen('cuatro.jpeg')
  const fila = [{ archivo: d, campos: { monto: '100,00', fecha: '01/07/2026' } }]
  await importarComprobantes(
    await jsonl('h1.jsonl', fila), corrida('h1'), { imagenes: dir, base: true })

  await db.query(
    `UPDATE comprobante SET monto = 777.00, revisado_en = now() WHERE archivo = 'cuatro.jpeg'`)

  await importarComprobantes(
    await jsonl('h2.jsonl', [{ archivo: d, campos: { monto: '250,00', fecha: '02/07/2026' } }]),
    corrida('h2'), { imagenes: dir, base: true })

  assert.equal((await comprobante('cuatro.jpeg')).monto, '777.00',
    'se perdió una corrección humana al reimportar')
})

test('un comprobante sin su imagen se cuenta y no rompe la importación', async () => {
  const e = await imagen('cinco.jpeg')
  const r = await importarComprobantes(
    await jsonl('falta.jsonl', [
      { archivo: 'no-existe.jpeg', campos: { monto: '1,00' } },
      { archivo: e, campos: { monto: '2,00' } },
    ]),
    corrida('falta'), { imagenes: dir })

  assert.equal(r.sinImagen, 1)
  assert.equal(r.extraccionesNuevas, 1, 'el que sí tenía imagen tiene que haber entrado')
})

test('reimportar la misma corrida no duplica extracciones', async () => {
  const f = await imagen('seis.jpeg')
  const ruta = await jsonl('rep.jsonl', [{ archivo: f, campos: { monto: '3,00' } }])
  await importarComprobantes(ruta, corrida('rep'), { imagenes: dir })
  const segunda = await importarComprobantes(ruta, corrida('rep'), { imagenes: dir })

  assert.equal(segunda.extraccionesNuevas, 0)
  assert.equal(segunda.yaEstaban, 1)
})

test('una fecha imposible no puede hacer perder la corrida entera', async () => {
  // El modelo alucina. Si un 30 de febrero tumba la transacción, se pierden los
  // otros 51 comprobantes de la corrida y no queda nada medido.
  const g = await imagen('siete.jpeg')
  const h = await imagen('ocho.jpeg')
  const r = await importarComprobantes(
    await jsonl('mal.jsonl', [
      { archivo: g, campos: { monto: '10,00', fecha: '30/02/2026' } },
      { archivo: h, campos: { monto: '20,00', fecha: '05/07/2026' } },
    ]),
    corrida('mal'), { imagenes: dir, base: true })

  assert.equal(r.extraccionesNuevas, 2, 'una fecha inválida se llevó puesta la corrida')
  assert.equal((await comprobante('siete.jpeg')).fecha, null,
    'una fecha que no existe va a NULL, no se inventa otra')
  assert.equal((await comprobante('ocho.jpeg')).fecha, '2026-07-05',
    'el comprobante sano tiene que haber entrado igual')
})

test('una hora imposible tampoco puede hacer perder la corrida', async () => {
  const i = await imagen('nueve.jpeg')
  const r = await importarComprobantes(
    await jsonl('hora.jsonl', [{ archivo: i, campos: { monto: '30,00', hora: '99:99' } }]),
    corrida('hora'), { imagenes: dir, base: true })

  assert.equal(r.extraccionesNuevas, 1, 'una hora inválida se llevó puesta la corrida')
  assert.equal((await comprobante('nueve.jpeg')).hora, null,
    'una hora que no existe va a NULL, no se inventa otra')
})
