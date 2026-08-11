'use server'

import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import { writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { extname, join } from 'node:path'
import { promisify } from 'node:util'
import { revalidatePath } from 'next/cache'
import { redirect } from 'next/navigation'
import { db } from '@/lib/db'
import { importarExtracto, type ResumenCuenta } from '@/lib/importar'
import { reconciliar, resolverAmbiguo } from '@/lib/conciliacion'
import { CAMPOS, type Campo } from '@/lib/importar-comprobantes'
import {
  guardarRevision as escribirRevision, cargarComprobante,
  aceptarFormato, proximo, type Filtro,
} from '@/lib/revision'

/** Las imágenes van al disco local, nunca a la base ni afuera de la máquina. */
const CARPETA = join(process.cwd(), 'comprobantes')

export type EstadoSubida =
  | { ok: true; resumen: ResumenCuenta[] }
  | { ok: false; error: string }
  | null

export async function subirExtracto(
  _previo: EstadoSubida, formData: FormData,
): Promise<EstadoSubida> {
  const archivo = formData.get('archivo')
  if (!(archivo instanceof File) || archivo.size === 0) {
    return { ok: false, error: 'Elegí un archivo .xlsx' }
  }
  try {
    const bytes = Buffer.from(await archivo.arrayBuffer())
    const resumen = await importarExtracto(bytes, archivo.name)
    await reconciliar() // los movimientos nuevos pueden resolver comprobantes viejos
    revalidatePath('/')
    return { ok: true, resumen }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Falló la importación' }
  }
}

export type EstadoComprobante =
  | { ok: true; id: number; estado: string }
  | { ok: false; error: string }
  | null

export async function guardarComprobante(
  _previo: EstadoComprobante, formData: FormData,
): Promise<EstadoComprobante> {
  const imagen = formData.get('imagen')
  if (!(imagen instanceof File) || imagen.size === 0) {
    return { ok: false, error: 'Falta la imagen del comprobante' }
  }

  try {
    const bytes = Buffer.from(await imagen.arrayBuffer())
    const hash = createHash('sha256').update(bytes).digest('hex')
    const nombre = `${hash.slice(0, 16)}-${imagen.name}`
    const crudos = Object.fromEntries(
      CAMPOS.map((c) => [c, formData.get(c) as string | null])) as Record<Campo, string | null>

    await mkdir(CARPETA, { recursive: true })
    await writeFile(join(CARPETA, nombre), bytes)

    // La imagen sobrevive solo si la fila entró. Al revés —fila sin imagen— la
    // pantalla de revisión queda mostrando un hueco y el comprobante no se
    // puede corregir nunca más.
    const r = await cargarComprobante(hash, nombre, crudos)
    if (!r.ok) {
      await rm(join(CARPETA, nombre), { force: true })
      return { ok: false, error: r.error }
    }

    await reconciliar()
    const { rows: [v] } = await db.query<{ estado: string }>(
      'SELECT estado FROM conciliacion WHERE comprobante_id = $1', [r.id])

    revalidatePath('/')
    return { ok: true, id: r.id, estado: v?.estado ?? 'sin veredicto' }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'No se pudo guardar' }
  }
}

/**
 * Lo que la pantalla de revisión tiene que mostrar después de mandar el
 * formulario. `null` mientras nadie lo mandó.
 *
 *   invalidos  → no se guardó NADA, hay que corregir y reintentar
 *   motivos    → se guardó, pero algún campo tiene una forma imposible
 *
 * Cuando guarda y no hay motivos no vuelve nada: la acción redirige al
 * siguiente, que es la señal de que salió bien.
 */
export type EstadoRevision =
  | { invalidos: Campo[] }
  | { guardado: number, motivos: string[] }
  | null

/**
 * La corrección humana de una extracción. La lógica y su prueba viven en
 * `lib/revision.ts`: acá queda solo lo que necesita el runtime de Next, que es
 * justo lo que impide testear este archivo.
 *
 * Si algún campo no se puede convertir, NO se escribe nada y se devuelve cuál
 * fue. Un campo de la IA se puede vaciar en silencio —el crudo sobrevive en
 * `extraccion.campos`—, pero de lo que escribió una persona no queda otra copia.
 */
export async function guardarRevision(
  _previo: EstadoRevision, formData: FormData,
): Promise<EstadoRevision> {
  const id = Number(formData.get('id'))
  const filtro = (formData.get('filtro') || 'pendientes') as Filtro
  // Lo escribe el `onClick` del botón *Guardar igual* en un campo oculto. Una
  // sola acción para los dos caminos, así el aviso de "no se pudo guardar" sale
  // igual por los dos.
  const aceptar = formData.get('aceptar') === '1'
  const crudos = Object.fromEntries(
    CAMPOS.map((c) => [c, formData.get(c) as string | null])) as Record<Campo, string | null>

  const r = await escribirRevision(id, crudos)
  if (!r.ok) return { invalidos: r.invalidos }
  if (aceptar) await aceptarFormato(id)

  await reconciliar()
  revalidatePath('/revisar')
  revalidatePath(`/revisar/${id}`)
  revalidatePath('/corridas')
  revalidatePath('/')

  // Quedarse es la única forma de mostrar el aviso: un redirect se lleva la
  // pantalla y la persona nunca se entera de que el campo sigue raro. Fue el bug
  // reportado — arreglar un CBU, guardar, y que el comprobante siguiera marcado.
  if (!aceptar && r.motivos.length > 0) return { guardado: id, motivos: r.motivos }

  // Sin nada raro, saltar al siguiente DEL MISMO FILTRO. Es la señal de que
  // guardó, y convierte revisar 51 comprobantes en una sola secuencia.
  const siguiente = await proximo(filtro, id)
  redirect(siguiente
    ? `/revisar/${siguiente}?filtro=${filtro}&guardado=${id}`
    : `/revisar?filtro=${filtro}&guardado=${id}`)
}

export async function elegirCandidato(formData: FormData) {
  const comprobante = Number(formData.get('comprobante'))
  const movimiento = Number(formData.get('movimiento'))
  await resolverAmbiguo(comprobante, movimiento)
  revalidatePath('/resolver')
  revalidatePath('/')
}

export async function recalcular() {
  await reconciliar()
  revalidatePath('/')
}

// ─── CBU propios ───────────────────────────────────────────────────────
// La regla, en palabras del usuario: "nuestro CBU no cambia. Puede que haya
// alguno nuevo, pero no va a ser lo más normal, por lo que ponelo como dudosa
// y que vaya a revisión manual".
//
// Ser dudoso NO se guarda en una columna: sale de preguntar si el
// `cbu_cvu_receptor` está en `cbu_propio`. Mismo criterio que `sin_comprobante`
// —no se guarda lo que se puede preguntar— y además así aprobar un CBU limpia
// solo todos los comprobantes que dependían de él, sin recalcular nada.

export async function agregarCbu(formData: FormData) {
  const cbu = String(formData.get('cbu') ?? '').replace(/\D/g, '')
  const nota = String(formData.get('nota') ?? '').trim() || null
  const cuenta = Number(formData.get('cuenta')) || null

  if (!/^\d{22}$/.test(cbu)) {
    redirect(`/cbu?error=${encodeURIComponent(
      `Un CBU/CVU tiene 22 dígitos y ese tiene ${cbu.length}. No se guardó nada.`)}`)
  }

  await db.query(
    `INSERT INTO cbu_propio (cbu, cuenta_id, nota) VALUES ($1, $2, $3)
     ON CONFLICT (cbu) DO UPDATE SET cuenta_id = EXCLUDED.cuenta_id,
                                     nota = coalesce(EXCLUDED.nota, cbu_propio.nota)`,
    [cbu, cuenta, nota])

  revalidatePath('/cbu')
  revalidatePath('/revisar')
  redirect('/cbu?ok=1')
}

export async function borrarCbu(formData: FormData) {
  await db.query('DELETE FROM cbu_propio WHERE id = $1', [Number(formData.get('id'))])
  revalidatePath('/cbu')
  revalidatePath('/revisar')
}

/** La raíz del proyecto: `next dev` corre con cwd en `web/`. */
const RAIZ = join(process.cwd(), '..')
const PYTHON = join(RAIZ, 'ia', '.venv', 'bin', 'python')

export type EstadoProbar =
  | {
      ok: true
      campos: Record<string, string | null>
      sinParsear: string | null
      adaptador: string
      segundos: number
    }
  | { ok: false; error: string }
  | null

/**
 * Corre `ia/extraer.py` sobre UNA imagen y devuelve los 16 campos.
 *
 * NO toca la base y NO deja la imagen en disco: va a un temporal que se borra
 * al terminar. Es un probador, no una carga. Así una foto de demo no puede
 * ensuciar los 51 comprobantes revisados a mano, que son la verdad de
 * referencia del proyecto y lo más caro de rehacer que tiene.
 *
 * Todo local: el modelo corre en esta máquina, nada sale de acá.
 */
export async function probarComprobante(
  _previo: EstadoProbar, formData: FormData,
): Promise<EstadoProbar> {
  const imagen = formData.get('imagen')
  if (!(imagen instanceof File) || imagen.size === 0) {
    return { ok: false, error: 'Elegí una foto del comprobante' }
  }

  // Un Server Action se alcanza con un POST directo, no solo desde la pantalla:
  // el nombre del adaptador se usa para armar una ruta y se valida acá.
  const adaptador = String(formData.get('adaptador') ?? '')
  if (adaptador && !/^[\w.-]+$/.test(adaptador)) {
    return { ok: false, error: 'Nombre de adaptador inválido' }
  }

  const carpeta = await mkdtemp(join(tmpdir(), 'probar-'))
  // La extensión no es cosmética: el cargador de imágenes elige el decoder con ella.
  const ruta = join(carpeta, `comprobante${extname(imagen.name) || '.jpeg'}`)
  const arranque = Date.now()
  try {
    await writeFile(ruta, Buffer.from(await imagen.arrayBuffer()))

    const args = ['ia/extraer.py', ruta, '--prompt', 'v3']
    if (adaptador) args.push('--adaptador', join('ia', 'checkpoints', adaptador))

    // 15 min: con un entrenamiento corriendo en paralelo la memoria se pelea y
    // un paso que suelto tarda 90 s puede irse a varios minutos.
    const { stdout } = await promisify(execFile)(PYTHON, args, {
      cwd: RAIZ, timeout: 15 * 60_000, maxBuffer: 10 << 20,
    })

    // `extraer.py` manda el progreso a stderr y una línea de JSON por imagen a
    // stdout. Acá va una sola imagen, así que es la última línea no vacía.
    const linea = stdout.trim().split('\n').filter(Boolean).at(-1)
    if (!linea) return { ok: false, error: 'El extractor no devolvió ninguna línea' }
    const r = JSON.parse(linea)

    return {
      ok: true,
      campos: r.campos ?? {},
      // Si el modelo no produjo JSON, se muestra lo que sí dijo. No lo encontró
      // no es lo mismo que no hay nada: el crudo deja ver cuál de las dos es.
      sinParsear: r.sin_parsear ?? null,
      adaptador: adaptador || 'modelo base (sin adaptador)',
      segundos: Math.round((Date.now() - arranque) / 1000),
    }
  } catch (e) {
    const err = e as { killed?: boolean; signal?: string; stderr?: string; message?: string }
    if (err.killed) {
      return { ok: false, error: 'Se pasó de los 15 minutos y se cortó. Suele ser memoria: mirá si hay un entrenamiento corriendo.' }
    }
    if (err.signal === 'SIGKILL') {
      return { ok: false, error: 'El sistema mató el proceso (SIGKILL). Es falta de memoria: el modelo son ~6 GB y hay un entrenamiento usando el resto.' }
    }
    const cola = (err.stderr ?? '').trim().split('\n').slice(-3).join(' · ')
    return { ok: false, error: cola || err.message || 'Falló la extracción' }
  } finally {
    await rm(carpeta, { recursive: true, force: true })
  }
}
