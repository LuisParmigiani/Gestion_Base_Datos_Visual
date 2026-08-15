/* Compara corridas sobre EXACTAMENTE los mismos comprobantes.
 *
 * `/corridas` mide cada corrida sobre los comprobantes que esa corrida tiene: v1 tiene
 * 51 y las del LoRA 16, así que sus porcentajes no se pueden poner uno al lado del otro.
 * Acá se restringe a la intersección — los 16 apartados — que es la única comparación
 * honesta contra la vara del 69%.
 *
 * Reusa `normalizarCampo` del importador a propósito: es el único camino por el que un
 * campo crudo se compara con la verdad. Una comparación paralela acá daría un número que
 * no coincide con el de la pantalla y no se sabría cuál creer.
 *
 *   node --env-file=.env.local comparar-lora.ts
 */
import { writeFile } from 'node:fs/promises'
import { db } from './src/lib/db.ts'
import { CAMPOS, type Campo, normalizarCampo } from './src/lib/importar-comprobantes.ts'

const CORRIDAS = ['v1', 'v2', 'v4', 'lora_v3_mejor', 'lora_v3_final', 'lora_v4_final',
                  'lora_v4_v2_final']
const REFERENCIA = 'lora_v3_mejor'   // define el conjunto de comprobantes a comparar

type Fila = {
  corrida: string
  comprobanteId: number
  banco: string | null
  ia: Record<string, string | null>
  verdad: Record<string, string | null>
}

const { rows } = await db.query<Fila>(
  `SELECT e.corrida, c.id AS "comprobanteId", c.banco_emisor AS banco, e.campos AS ia,
          jsonb_build_object(
            'tipo_operacion', c.tipo_operacion, 'monto', c.monto::text,
            'moneda', c.moneda, 'fecha', to_char(c.fecha,'YYYY-MM-DD'),
            'hora', to_char(c.hora,'HH24:MI'),
            'nombre_emisor', c.nombre_emisor, 'cuit_emisor', c.cuit_emisor,
            'cbu_cvu_emisor', c.cbu_cvu_emisor, 'banco_emisor', c.banco_emisor,
            'nombre_receptor', c.nombre_receptor, 'cuit_receptor', c.cuit_receptor,
            'cbu_cvu_receptor', c.cbu_cvu_receptor, 'banco_receptor', c.banco_receptor,
            'concepto', c.concepto, 'referencia', c.referencia, 'coelsa_id', c.coelsa_id
          ) AS verdad
   FROM comprobante c JOIN extraccion e ON e.comprobante_id = c.id
   WHERE c.revisado_en IS NOT NULL`)

// Los comprobantes a comparar: los que tiene la corrida de referencia. Cualquier corrida
// a la que le falte alguno se descarta con un aviso, en vez de compararse sobre menos.
const ids = new Set(rows.filter((r) => r.corrida === REFERENCIA).map((r) => r.comprobanteId))
const acierta = (r: Fila, campo: Campo) =>
  normalizarCampo(campo, r.ia[campo]) === normalizarCampo(campo, r.verdad[campo])

const de = (corrida: string) => rows.filter((r) => r.corrida === corrida && ids.has(r.comprobanteId))

console.log(`\ncomparando sobre ${ids.size} comprobantes revisados · ${CAMPOS.length} campos ` +
            `= ${ids.size * CAMPOS.length} campos por corrida\n`)

console.log('TOTAL')
for (const c of CORRIDAS) {
  const filas = de(c)
  if (filas.length !== ids.size) { console.log(`  ${c.padEnd(15)} SE OMITE: tiene ${filas.length} de ${ids.size}`); continue }
  const ok = filas.reduce((n, r) => n + CAMPOS.filter((k) => acierta(r, k)).length, 0)
  const total = ids.size * CAMPOS.length
  console.log(`  ${c.padEnd(15)} ${String(ok).padStart(3)}/${total}  ${(100 * ok / total).toFixed(1)}%`)
}

// Dos cortes que separan el rendimiento real del ruido de medición:
//  - sin `tipo_operacion`: el LoRA contesta `transferencia_saliente` (el vocabulario del
//    generador sintético) donde la verdad dice `Transferencia`. Acierta los 16 y cuenta 0.
//    Es un desajuste de etiquetas del dataset, no de lectura.
//  - sin Mercado Pago: 9 de los 16 apartados son de una sola entidad, así que el total
//    global mide sobre todo qué tan bien se lee Mercado Pago.
const cortes: [string, (r: Fila) => boolean, Campo[]][] = [
  ['sin tipo_operacion', () => true, CAMPOS.filter((c) => c !== 'tipo_operacion')],
  ['sin Mercado Pago', (r) => !(r.banco ?? '').toLowerCase().includes('mercado pago'), CAMPOS],
  ['solo Mercado Pago', (r) => (r.banco ?? '').toLowerCase().includes('mercado pago'), CAMPOS],
  // Los seis que deciden la conciliación. Los otros diez son contexto útil, pero que el
  // modelo falle `concepto` (texto libre) no cambia si un comprobante cruza o no.
  ['solo los campos que deciden la conciliación', () => true,
   ['monto', 'fecha', 'moneda', 'cuit_emisor', 'cbu_cvu_receptor', 'referencia'] as Campo[]],
]
for (const [titulo, filtro, campos] of cortes) {
  console.log(`\nTOTAL — ${titulo}`)
  for (const c of CORRIDAS) {
    const filas = de(c).filter(filtro)
    if (filas.length === 0) continue
    const ok = filas.reduce((n, r) => n + campos.filter((k) => acierta(r, k)).length, 0)
    const total = filas.length * campos.length
    console.log(`  ${c.padEnd(15)} ${String(ok).padStart(3)}/${total}  ${(100 * ok / total).toFixed(1)}%`)
  }
}

console.log('\nPOR CAMPO')
const cabecera = CORRIDAS.filter((c) => de(c).length === ids.size)
console.log(`  ${'campo'.padEnd(18)}${cabecera.map((c) => c.slice(0, 13).padStart(15)).join('')}`)
for (const campo of CAMPOS) {
  const celdas = cabecera.map((c) => {
    const filas = de(c)
    const ok = filas.filter((r) => acierta(r, campo)).length
    return `${ok}/${filas.length}`.padStart(15)
  })
  console.log(`  ${campo.padEnd(18)}${celdas.join('')}`)
}

console.log('\nPOR ENTIDAD EMISORA (la de la verdad corregida, no la que dijo el modelo)')
const norm = (b: string | null) => {
  const s = (b ?? 'sin dato').toLowerCase()
  return ['macro', 'mercado pago', 'galicia', 'santander', 'nación', 'brubank'].find((k) => s.includes(k)) ?? s
}
const entidades = [...new Set(rows.filter((r) => ids.has(r.comprobanteId)).map((r) => norm(r.banco)))].sort()
console.log(`  ${'entidad'.padEnd(15)}${'n'.padStart(4)}${cabecera.map((c) => c.slice(0, 13).padStart(15)).join('')}`)
for (const ent of entidades) {
  const celdas = cabecera.map((c) => {
    const filas = de(c).filter((r) => norm(r.banco) === ent)
    const ok = filas.reduce((n, r) => n + CAMPOS.filter((k) => acierta(r, k)).length, 0)
    const total = filas.length * CAMPOS.length
    return `${(100 * ok / total).toFixed(0)}% (${ok}/${total})`.padStart(15)
  })
  const n = de(REFERENCIA).filter((r) => norm(r.banco) === ent).length
  console.log(`  ${ent.padEnd(15)}${String(n).padStart(4)}${celdas.join('')}`)
}

// El CSV que consume Looker Studio: UNA fila por corrida × comprobante × campo. En formato
// largo a propósito — con esas cuatro dimensiones el tablero arma solo el corte por campo,
// por entidad y sin `tipo_operacion`, así que no hay que exportar un archivo por vista ni
// mantener acá los mismos cortes dos veces.
const q = (s: string) => `"${s.replace(/"/g, '""')}"`   // la entidad puede traer una coma
const csv = ['corrida,comprobante_id,entidad,campo,acierto']
for (const c of cabecera)
  for (const r of de(c))
    for (const campo of CAMPOS)
      csv.push([c, r.comprobanteId, q(norm(r.banco)), campo, acierta(r, campo) ? 1 : 0].join(','))

const salida = new URL('../metricas/extraccion.csv', import.meta.url)
await writeFile(salida, csv.join('\n') + '\n')
console.log(`\n${csv.length - 1} filas → metricas/extraccion.csv`)

await db.end()
