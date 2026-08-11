import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { basename, dirname, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { db } from './db.ts'
import { parsearImporte } from './extracto.ts'

/** Los 16 campos, en el orden de la tabla `comprobante`. */
export const CAMPOS = [
  'tipo_operacion', 'monto', 'moneda', 'fecha', 'hora',
  'nombre_emisor', 'cuit_emisor', 'cbu_cvu_emisor', 'banco_emisor',
  'nombre_receptor', 'cuit_receptor', 'cbu_cvu_receptor', 'banco_receptor',
  'concepto', 'referencia', 'coelsa_id',
] as const

export type Campo = typeof CAMPOS[number]
type Campos = Partial<Record<Campo, string | null>>

export type Corrida = {
  nombre: string
  descripcion: string
  modelo: string
  prompt?: string | null
  adaptador?: string | null
  cambioRespectoDe?: string | null
  queCambio?: string | null
}

export type ResumenComprobantes = {
  leidos: number
  comprobantesNuevos: number
  extraccionesNuevas: number
  yaEstaban: number
  sinImagen: number
}

/**
 * Lee las dos formas de JSONL que produce `ia/` y devuelve la misma cosa.
 *
 *   salida_vN / validado   {"archivo": "001.jpeg", "campos": {…16…}}
 *   train.jsonl            {"images": ["ruta.jpg"], "messages": [… assistant: "{…16…}"]}
 */
function normalizar(linea: string): { archivo: string, campos: Campos } | null {
  const r = JSON.parse(linea)
  if (r.campos) return { archivo: r.archivo, campos: r.campos }
  if (r.images && r.messages) {
    const respuesta = r.messages.find((m: { role: string }) => m.role === 'assistant')
    return { archivo: r.images[0], campos: JSON.parse(respuesta.content) }
  }
  return null
}

/** `''` y `'N/A'` son ausencia, no valor. El modelo devuelve las dos cosas. */
const oNulo = (v: unknown): string | null => {
  const s = v === null || v === undefined ? '' : String(v).trim()
  return s === '' || s.toUpperCase() === 'N/A' ? null : s
}

/**
 * El crudo del modelo no entra en columnas tipadas: devuelve `$ 81.687,80`
 * para un NUMERIC, `27/06/2026` para un DATE y `19:16 hs` para un TIME.
 *
 * Lo que no se puede convertir SIN ADIVINAR queda en NULL. `$ 1.500` puede ser
 * mil quinientos o uno con cincuenta, y `parsearImporte` ya lo marca ambiguo:
 * se respeta. El valor crudo no se pierde — vive entero en `extraccion.campos`.
 */
const aNumero = (v: string | null): string | null => {
  if (v === null) return null
  const { importe, ambiguo } = parsearImporte(v)
  if (ambiguo || importe === null) return null
  // NUMERIC(14,2) admite 12 dígitos enteros. Cuando el modelo confunde el monto
  // con un CBU de 22 dígitos, el valor no entra. Va a NULL: truncarlo sería
  // inventar un importe, que es exactamente lo que el proyecto prohíbe.
  const enteros = importe.replace('-', '').split('.')[0].length
  return enteros > 12 ? null : importe
}

/**
 * La forma no alcanza: `30/02/2026` la cumple y esa fecha no existe. Postgres
 * la rechaza con 22008 y, como todo esto es UNA transacción, el ROLLBACK se
 * lleva la corrida entera — 52 comprobantes perdidos por uno alucinado.
 *
 * El ida y vuelta por `Date` lo delata: un 30 de febrero se normaliza a marzo,
 * así que deja de coincidir consigo mismo.
 */
const aFecha = (v: string | null): string | null => {
  if (v === null) return null
  const dmy = v.match(/^(\d{2})[/-](\d{2})[/-](\d{4})$/)
  const iso = dmy ? `${dmy[3]}-${dmy[2]}-${dmy[1]}`
    : /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null
  if (iso === null) return null
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime()) || !d.toISOString().startsWith(iso) ? null : iso
}

/** Mismo motivo que `aFecha`: `99:99` cumple la forma y no es una hora. */
const aHora = (v: string | null): string | null =>
  v === null ? null : (v.match(/^([01]?\d|2[0-3]):([0-5]\d)/)?.slice(1).join(':') ?? null)

/**
 * Un campo crudo → lo que va en su columna. Los tres campos tipados se
 * convierten; los otros 13 son TEXT y van tal cual.
 *
 * `invalido` separa dos cosas que terminan igual pero no son lo mismo: el campo
 * vino vacío, o vino algo que no se puede convertir sin adivinar. Para la IA
 * los dos van a NULL y el crudo sobrevive en `extraccion.campos`. Para una
 * corrección humana no: si no se puede guardar hay que avisarlo, porque no
 * queda ninguna otra copia de lo que la persona escribió.
 */
export function paraColumna(
  campo: Campo, valor: unknown,
): { valor: string | null, invalido: boolean } {
  const v = oNulo(valor)
  if (v === null) return { valor: null, invalido: false }
  const convertido = campo === 'monto' ? aNumero(v)
    : campo === 'fecha' ? aFecha(v)
    : campo === 'hora' ? aHora(v)
    : v
  return { valor: convertido, invalido: convertido === null }
}

/**
 * Un campo crudo, en la forma en que se COMPARA. No es lo que se guarda.
 *
 * Comparar el crudo contra la columna SIN pasar por acá da diferencias falsas:
 * el modelo escribe `$ 81.687,80` y la columna NUMERIC guarda `81687.80`.
 * Son el mismo valor y el modelo acertó. Lo usan el importador, la pantalla de
 * revisión y la tabla de aciertos, y tienen que usar los tres el mismo.
 *
 * Los 13 campos de texto se pliegan a minúsculas. `banco de galicia` y
 * `Banco De Galicia` son el mismo banco: lo que se mide es si el modelo puso el
 * dato correcto en el campo correcto, no cómo lo capitalizó. Decisión del
 * 2026-08-11, medida sobre los 16 apartados: eran 14 falsos errores en
 * `lora_v3_final` contra 3 en el modelo base — o sea que la mayúscula le estaba
 * cobrando al LoRA una desventaja que no existía.
 *
 * ⚠️ El plegado vive ACÁ y no en `paraColumna` a propósito: la base guarda
 * exactamente lo que tipeó la persona en `/revisar`, que es la verdad de
 * referencia del proyecto y no se reescribe para acomodar una comparación.
 */
export function normalizarCampo(campo: Campo, valor: unknown): string {
  const { valor: v } = paraColumna(campo, valor)
  if (v === null) return ''
  // NUMERIC(14,2) siempre devuelve dos decimales: '250000' y '250000.00' son
  // el mismo importe y no pueden contar como una corrección.
  if (campo === 'monto') return Number(v).toFixed(2)
  // `fecha` y `hora` ya salen canónicas de `paraColumna`; el resto es texto.
  return campo === 'fecha' || campo === 'hora' ? v : v.toLowerCase()
}

const paraColumnas = (campos: Campos): (string | null)[] =>
  CAMPOS.map((c) => paraColumna(c, campos[c]).valor)

/**
 * JSONL de una corrida → tablas `corrida`, `extraccion` y `comprobante`.
 *
 * El comprobante se crea una sola vez (lo identifica el hash de la imagen).
 * Cada corrida agrega su fila en `extraccion` y **nunca pisa** las anteriores:
 * comparar corridas es lo único que responde si el modelo mejoró.
 *
 * `base: true` hace que esta corrida siembre las columnas tipadas del
 * comprobante — las que una persona después corrige en /revisar.
 */
export async function importarComprobantes(
  jsonl: string,
  corrida: Corrida,
  opciones: { imagenes?: string, base?: boolean } = {},
): Promise<ResumenComprobantes> {
  const lineas = (await readFile(jsonl, 'utf8')).split('\n').filter(l => l.trim())
  const baseImagenes = opciones.imagenes ?? dirname(resolve(jsonl))

  let comprobantesNuevos = 0, extraccionesNuevas = 0, yaEstaban = 0, sinImagen = 0
  const cliente = await db.connect()
  try {
    await cliente.query('BEGIN')

    await cliente.query(
      `INSERT INTO corrida (nombre, descripcion, modelo, prompt, adaptador,
                            cambio_respecto_de, que_cambio)
       VALUES ($1,$2,$3,$4,$5,$6,$7)
       ON CONFLICT (nombre) DO UPDATE SET
         descripcion = EXCLUDED.descripcion, modelo = EXCLUDED.modelo,
         prompt = EXCLUDED.prompt, adaptador = EXCLUDED.adaptador,
         cambio_respecto_de = EXCLUDED.cambio_respecto_de,
         que_cambio = EXCLUDED.que_cambio`,
      [corrida.nombre, corrida.descripcion, corrida.modelo, corrida.prompt ?? null,
        corrida.adaptador ?? null, corrida.cambioRespectoDe ?? null, corrida.queCambio ?? null])

    for (const linea of lineas) {
      const reg = normalizar(linea)
      if (!reg) continue

      // El hash es del archivo, no del JSON: es lo que hace que la misma imagen
      // en dos corridas sea UN comprobante con dos extracciones, y no dos.
      const ruta = reg.archivo.includes('/') ? reg.archivo : resolve(baseImagenes, reg.archivo)
      let bytes: Buffer
      try {
        bytes = await readFile(ruta)
      } catch {
        sinImagen++
        continue
      }
      const hash = createHash('sha256').update(bytes).digest('hex')
      const valores = paraColumnas(reg.campos)

      const nuevo = await cliente.query<{ id: number }>(
        `INSERT INTO comprobante (archivo, hash_imagen, origen, estado_extraccion, corrida_base,
           ${CAMPOS.join(', ')})
         VALUES ($1,$2,'ia','extraido',$3,
           $4,$5::numeric,$6,$7::date,$8::time,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
         ON CONFLICT (hash_imagen) DO NOTHING
         RETURNING id`,
        [basename(ruta), hash, opciones.base ? corrida.nombre : null, ...valores])

      let id: number
      if (nuevo.rowCount === 1) {
        id = nuevo.rows[0].id
        comprobantesNuevos++
      } else {
        const { rows } = await cliente.query<{ id: number }>(
          'SELECT id FROM comprobante WHERE hash_imagen = $1', [hash])
        id = rows[0].id
        // Una corrida marcada como base siembra las columnas tipadas aunque el
        // comprobante ya existiera — salvo que una persona ya lo haya revisado,
        // porque ahí las columnas son la corrección humana y no se tocan.
        if (opciones.base) {
          await cliente.query(
            `UPDATE comprobante SET corrida_base = $1,
               ${CAMPOS.map((c, i) => `${c} = $${i + 2}`).join(', ')}
             WHERE id = $18 AND revisado_en IS NULL`,
            [corrida.nombre, ...valores, id])
        }
      }

      const ext = await cliente.query(
        `INSERT INTO extraccion (comprobante_id, corrida, campos) VALUES ($1,$2,$3)
         ON CONFLICT (comprobante_id, corrida) DO NOTHING`,
        [id, corrida.nombre, JSON.stringify(reg.campos)])
      if (ext.rowCount === 1) extraccionesNuevas++; else yaEstaban++
    }

    await cliente.query('COMMIT')
  } catch (e) {
    await cliente.query('ROLLBACK')
    throw e
  } finally {
    cliente.release()
  }
  return { leidos: lineas.length, comprobantesNuevos, extraccionesNuevas, yaEstaban, sinImagen }
}

// ponytail: el mismo patrón de CLI corto que `importar.ts`, con parseArgs de la
// stdlib en vez de una librería de flags.
if ((import.meta as { main?: boolean }).main) {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      desc: { type: 'string' }, modelo: { type: 'string' }, prompt: { type: 'string' },
      adaptador: { type: 'string' }, 'respecto-de': { type: 'string' },
      cambio: { type: 'string' }, imagenes: { type: 'string' },
      base: { type: 'boolean' },
    },
  })
  const [jsonl, nombre] = positionals
  if (!jsonl || !nombre) {
    console.error('uso: pnpm importar:comprobantes <archivo.jsonl> <corrida> \\\n' +
      '       --desc "qué es" [--modelo M] [--prompt v3] [--adaptador ruta] \\\n' +
      '       [--respecto-de corrida --cambio "qué cambió"] [--imagenes dir] [--base]')
    process.exit(1)
  }
  const r = await importarComprobantes(jsonl, {
    nombre,
    descripcion: values.desc ?? nombre,
    modelo: values.modelo ?? 'mlx-community/Qwen2-VL-7B-Instruct-4bit',
    prompt: values.prompt,
    adaptador: values.adaptador,
    cambioRespectoDe: values['respecto-de'],
    queCambio: values.cambio,
  }, { imagenes: values.imagenes, base: values.base })
  console.log(`leídos ${r.leidos} · comprobantes nuevos ${r.comprobantesNuevos} · ` +
    `extracciones nuevas ${r.extraccionesNuevas} · ya estaban ${r.yaEstaban} · ` +
    `sin imagen ${r.sinImagen}`)
  await db.end()
}
