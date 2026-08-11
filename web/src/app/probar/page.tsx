import { readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { Formulario } from './formulario'

export const dynamic = 'force-dynamic'

/**
 * Los adaptadores entrenados que hay en disco, ahora mismo.
 *
 * Un checkpoint a medio entrenar también sirve para probar: `entrenar.py`
 * escribe `adapters.safetensors` de forma atómica en cada paso, así que leerlo
 * mientras la corrida avanza no da un archivo partido.
 */
async function adaptadores(): Promise<string[]> {
  const raiz = join(process.cwd(), '..', 'ia', 'checkpoints')
  const entradas = await readdir(raiz, { withFileTypes: true }).catch(() => [])
  const encontrados = await Promise.all(
    entradas.filter((e) => e.isDirectory()).map(async (e) => {
      const archivos = await readdir(join(raiz, e.name)).catch((): string[] => [])
      return archivos.includes('adapters.safetensors') ? e.name : null
    }),
  )
  return encontrados.filter((d): d is string => d !== null).sort()
}

export default async function Probar() {
  return <Formulario adaptadores={await adaptadores()} />
}
