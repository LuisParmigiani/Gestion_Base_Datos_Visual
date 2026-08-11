import { db } from './db.ts'
import { CAMPOS, type Campo, paraColumna } from './importar-comprobantes.ts'

/**
 * Lo que una persona escribe sobre un comprobante: corregir lo que extrajo el
 * modelo, o cargar uno entero a mano. Es la pieza que produce la verdad de
 * referencia del proyecto — sirve a la vez para medir el modelo y para
 * entrenarlo, y es lo más caro de rehacer que hay acá: son 51 comprobantes
 * revisados a mano, campo por campo.
 *
 * Vive en `lib/` y no adentro de la Server Action por un motivo práctico:
 * `next/cache` no resuelve fuera del bundler de Next, así que nada que lo
 * importe se puede probar con `node --test`. Acá sí, contra `conciliador_test`,
 * igual que `importarExtracto` y `reconciliar`.
 *
 * Escribe SOLO las columnas tipadas de `comprobante`. `extraccion.campos` —lo
 * que contestó el modelo— no se toca nunca: si se pisara, no quedaría contra
 * qué comparar y la medición dejaría de significar algo.
 */

export type ResultadoRevision =
  | { ok: true, siguiente: number | null, motivos: string[] }
  | { ok: false, invalidos: Campo[] }

/** El nombre de cada campo en pantalla. Vive acá porque los avisos lo usan. */
export const ETIQUETAS: Record<Campo, string> = {
  tipo_operacion: 'Tipo de operación', monto: 'Monto', moneda: 'Moneda',
  fecha: 'Fecha', hora: 'Hora',
  nombre_emisor: 'Nombre del emisor', cuit_emisor: 'CUIT del emisor',
  cbu_cvu_emisor: 'CBU/CVU del emisor', banco_emisor: 'Banco del emisor',
  nombre_receptor: 'Nombre del receptor', cuit_receptor: 'CUIT del receptor',
  cbu_cvu_receptor: 'CBU/CVU del receptor', banco_receptor: 'Banco del receptor',
  concepto: 'Concepto', referencia: 'Referencia', coelsa_id: 'ID COELSA',
}

/** Cuántos dígitos tiene que tener cada uno. Los separadores no cuentan. */
const LARGOS: Partial<Record<Campo, number>> = {
  cuit_emisor: 11, cuit_receptor: 11, cbu_cvu_emisor: 22, cbu_cvu_receptor: 22,
}

/** Lo que el modelo devuelve como texto cuando quiere decir "no hay". */
const NO_ES_VALOR = new Set(['null', 'n/a', 'none'])

/**
 * Qué campos tienen una forma imposible. Lista vacía = no hay nada que mirar.
 *
 * NO detecta errores: detecta formas que no pueden ser. Un CUIT tiene 11 dígitos
 * y un CBU/CVU tiene 22 — si hay otra cosa, o la imagen mostraba el número
 * cortado, o se perdió un dígito al transcribir. Los dos casos quieren que una
 * persona lo mire, y solo una persona puede distinguirlos: por eso esto avisa y
 * nunca corrige.
 *
 * Un campo vacío no se marca. "No figura en el comprobante" es información.
 *
 * Devuelve TODOS los motivos, no el primero: el bug que lo motivó fue arreglar
 * un CBU, guardar, y que el comprobante siguiera marcado porque el CUIT también
 * estaba mal y la pantalla no lo decía.
 *
 * ponytail: sin dígito verificador de CUIT ni de CBU. Los dos existen y
 * atraparían más, pero son ~20 líneas de aritmética para un puñado de casos que
 * igual hay que mirar contra la imagen. Si aparecen muchos largos correctos con
 * números inventados, ahí sí vale.
 */
export function motivosDeFormato(crudos: Crudos): string[] {
  const motivos: string[] = []
  for (const campo of CAMPOS) {
    const v = (crudos[campo] ?? '').trim()
    if (!v) continue
    if (NO_ES_VALOR.has(v.toLowerCase())) {
      motivos.push(`${ETIQUETAS[campo]}: dice "${v}", que no es un valor`)
      continue
    }
    const esperados = LARGOS[campo]
    if (esperados === undefined) continue
    const digitos = v.replace(/\D/g, '').length
    if (digitos !== esperados) {
      motivos.push(`${ETIQUETAS[campo]}: ${digitos} dígitos, se esperan ${esperados}`)
    }
  }
  return motivos
}

export type ResultadoCarga =
  | { ok: true, id: number }
  | { ok: false, error: string, invalidos?: Campo[] }

/** Los 16 campos crudos, como los manda un formulario: todo texto. */
type Crudos = Partial<Record<Campo, string | null>>

/**
 * Los 16 campos convertidos a lo que va en cada columna, o cuáles no se
 * pudieron. Todo o nada: guardar 15 campos y perder uno en silencio es lo peor
 * que puede pasar acá, porque la persona se va creyendo que lo cargó entero y
 * de lo que escribió no queda ninguna otra copia.
 */
function convertir(crudos: Crudos): { valores: (string | null)[] } | { invalidos: Campo[] } {
  const convertidos = CAMPOS.map((c) => paraColumna(c, crudos[c]))
  const invalidos = CAMPOS.filter((_, i) => convertidos[i].invalido)
  return invalidos.length > 0 ? { invalidos } : { valores: convertidos.map((c) => c.valor) }
}

/** Pendiente = sin revisar y con corrida contra la cual comparar. Los sintéticos
 *  no cuentan: su etiqueta la generó un script, no son verdad de referencia. */
const PENDIENTE =
  "revisado_en IS NULL AND corrida_base IS NOT NULL AND corrida_base <> 'sintetico'"

/** El próximo a revisar después de `id`, dando la vuelta al llegar al final. */
export async function proximoPendiente(id: number): Promise<number | null> {
  const { rows } = await db.query<{ id: number }>(
    `SELECT id FROM comprobante WHERE ${PENDIENTE} AND id > $1 ORDER BY id LIMIT 1`, [id])
  if (rows[0]) return rows[0].id
  const { rows: desdeElPrincipio } = await db.query<{ id: number }>(
    `SELECT id FROM comprobante WHERE ${PENDIENTE} ORDER BY id LIMIT 1`)
  return desdeElPrincipio[0]?.id ?? null
}

export async function guardarRevision(id: number, crudos: Crudos): Promise<ResultadoRevision> {
  const r = convertir(crudos)
  if ('invalidos' in r) return { ok: false, invalidos: r.invalidos }

  // `formato_aceptado_en` vuelve a NULL: si la persona editó, la pregunta se
  // reabre. Aceptar una forma rara vale para el valor que se aceptó, no para
  // cualquiera que venga después.
  await db.query(
    `UPDATE comprobante SET revisado_en = now(), estado_extraccion = 'confirmado',
       formato_aceptado_en = NULL,
       ${CAMPOS.map((c, i) => `${c} = $${i + 2}`).join(', ')}
     WHERE id = $1`,
    [id, ...r.valores])

  return { ok: true, siguiente: await proximoPendiente(id), motivos: motivosDeFormato(crudos) }
}

/** "Ya lo miré: el comprobante dice eso". Lo escribe el botón *Guardar igual*. */
export async function aceptarFormato(id: number): Promise<void> {
  await db.query('UPDATE comprobante SET formato_aceptado_en = now() WHERE id = $1', [id])
}

export type Filtro = 'pendientes' | 'revisados' | 'dudas' | 'todos'

/** Un comprobante de la cola, con lo que hace falta para juzgarlo. */
export type EnCola = {
  id: number
  revisado: boolean
  aceptado: boolean
  motivos: string[]
}

/**
 * ¿Este comprobante entra en ese filtro?
 *
 * Exportado porque lo usan la lista (para contar y mostrar) y `proximo` (para
 * saber a dónde saltar). Si cada uno tuviera su copia, el día que cambie una
 * regla la lista y el recorrido dirían cosas distintas y nadie lo notaría.
 */
export const entra = (f: EnCola, filtro: Filtro): boolean =>
  filtro === 'todos' ? true
    : filtro === 'pendientes' ? !f.revisado
      : filtro === 'revisados' ? f.revisado
        // Aceptado a mano = deja de pedir atención. Sin eso la lista de dudas
        // nunca podría llegar a cero, que es lo único que la hace una cola.
        : f.revisado && !f.aceptado && f.motivos.length > 0

/**
 * Los comprobantes REALES, en el orden en que se recorren.
 *
 * "dudas" no se puede resolver con un WHERE: el chequeo de forma vive en
 * TypeScript y tiene que vivir en un solo lugar. Son 51 filas — traerlas y
 * filtrarlas acá cuesta menos que mantener la misma regla escrita dos veces.
 */
export async function cola(filtro: Filtro = 'todos'): Promise<EnCola[]> {
  const { rows } = await db.query<{ id: number, revisado: boolean, aceptado: boolean }
    & Record<Campo, string | null>>(
    `SELECT id, revisado_en IS NOT NULL AS revisado,
            formato_aceptado_en IS NOT NULL AS aceptado,
            ${CAMPOS.filter((c) => !['monto', 'fecha', 'hora'].includes(c)).join(', ')},
            monto::text, to_char(fecha,'YYYY-MM-DD') AS fecha, to_char(hora,'HH24:MI') AS hora
     FROM comprobante
     WHERE corrida_base IS NOT NULL AND corrida_base <> 'sintetico'
     -- Por id y nada más. Cualquier orden que dependa de revisado_en se REORDENA
     -- al guardar —el comprobante salta al grupo de los revisados, o al final por
     -- timestamp— y entonces "el que sigue" pasa a ser otro en cada guardado.
     -- Revisar 51 es una pasada: la cola no se puede mover mientras se camina.
     -- Las pestañas ya separan pendientes de revisados, así que agrupar de nuevo
     -- acá no aportaba nada.
     ORDER BY id`)

  return rows
    .map((f) => ({
      id: f.id, revisado: f.revisado, aceptado: f.aceptado, motivos: motivosDeFormato(f),
    }))
    .filter((f) => entra(f, filtro))
}

/**
 * El próximo del MISMO filtro en que está trabajando la persona.
 *
 * Siempre hacia ADELANTE, nunca al principio: revisar 51 comprobantes es una
 * pasada, y volver al primero después de guardar hace imposible saber por dónde
 * se iba. Tres casos, en este orden:
 *
 *   1. El comprobante sigue en la cola  → el que va después.
 *   2. Salió de la cola (se arregló)    → el primero con id mayor.
 *   3. No queda nada en ESE filtro      → se busca en "todos".
 *
 * El (3) es el bug que hacía que guardar no llevara a ningún lado: con los 51 ya
 * revisados la cola de "pendientes" está vacía, y una URL sin `?filtro=` caía
 * ahí y devolvía `null`. Mientras quede un comprobante para revisar, guardar
 * tiene que llevar a alguno.
 */
export async function proximo(filtro: Filtro, id: number): Promise<number | null> {
  const ids = (await cola(filtro)).map((f) => f.id)
  const i = ids.indexOf(id)
  const siguiente = i >= 0 ? ids[i + 1] : ids.find((x) => x > id)
  if (siguiente !== undefined) return siguiente
  // Si el filtro se quedó sin nada, no se abandona a la persona en la lista:
  // se sigue por la cola completa. Solo devuelve null cuando de verdad no hay
  // ningún otro comprobante después de éste.
  if (filtro === 'todos') return null
  const todos = (await cola('todos')).map((f) => f.id)
  return todos.find((x) => x > id) ?? null
}

/**
 * Un comprobante cargado a mano, sin IA de por medio. La imagen la escribe al
 * disco quien llama: acá solo entra su hash, que es lo que detecta el reenvío
 * de la misma imagen.
 */
export async function cargarComprobante(
  hash: string, archivo: string, crudos: Crudos,
): Promise<ResultadoCarga> {
  // Sin monto o sin fecha no hay con qué cruzar contra el extracto.
  if (!crudos.monto?.trim() || !crudos.fecha?.trim()) {
    return { ok: false, error: 'El monto y la fecha son obligatorios: sin eso no se puede cruzar' }
  }

  const r = convertir(crudos)
  if ('invalidos' in r) {
    return {
      ok: false, invalidos: r.invalidos,
      error: `No se pudo interpretar: ${r.invalidos.join(', ')}. `
        + 'Un valor que necesita adivinarse no se guarda — $ 1.500 puede ser mil quinientos '
        + 'o uno con cincuenta. No se cargó nada.',
    }
  }

  const { rows: [repetido] } = await db.query<{ id: number }>(
    'SELECT id FROM comprobante WHERE hash_imagen = $1', [hash])
  if (repetido) {
    return { ok: false, error: `Esa misma imagen ya se cargó (comprobante ${repetido.id})` }
  }

  const { rows: [fila] } = await db.query<{ id: number }>(
    `INSERT INTO comprobante (archivo, hash_imagen, origen, estado_extraccion, ${CAMPOS.join(', ')})
     VALUES ($1, $2, 'manual', 'confirmado',
       ${CAMPOS.map((_, i) => `$${i + 3}`).join(', ')})
     RETURNING id`,
    [archivo, hash, ...r.valores])

  return { ok: true, id: fila.id }
}
