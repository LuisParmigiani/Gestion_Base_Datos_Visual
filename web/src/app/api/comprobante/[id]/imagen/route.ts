import { readFile } from 'node:fs/promises'
import { basename, extname, resolve } from 'node:path'
import { db } from '@/lib/db'

/**
 * Sirve la imagen de un comprobante, de a una.
 *
 * Por qué un route handler y no `web/public/`: los comprobantes reales viven
 * en `ia/comprobantes/`. Copiarlos a `public/` los publicaría a todos juntos —
 * con `pnpm dev` escuchando, cualquiera en la red local podría listar la
 * carpeta. Acá se lee de disco la que se pide y nada más.
 */

// ponytail: dos directorios conocidos en vez de guardar la ruta completa en la
// base. Si aparece un tercero, agregar la columna `ruta` a `comprobante`.
const DIRECTORIOS = [
  resolve(process.cwd(), '../ia/comprobantes'),
  resolve(process.cwd(), '../ia/sinteticos/imagenes'),
]

const TIPOS: Record<string, string> = {
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
}

export async function GET(_req: Request, ctx: RouteContext<'/api/comprobante/[id]/imagen'>) {
  const { id } = await ctx.params

  const { rows } = await db.query<{ archivo: string }>(
    'SELECT archivo FROM comprobante WHERE id = $1', [id])
  if (rows.length === 0) return new Response('no existe', { status: 404 })

  // basename aunque la base ya lo guarde así: es lo único que separa esto de
  // servir cualquier archivo de la máquina con un ../../ en el nombre.
  const archivo = basename(rows[0].archivo)
  const tipo = TIPOS[extname(archivo).toLowerCase()]
  if (!tipo) return new Response('formato no soportado', { status: 415 })

  for (const dir of DIRECTORIOS) {
    try {
      const bytes = await readFile(resolve(dir, archivo))
      return new Response(new Uint8Array(bytes), {
        headers: {
          'Content-Type': tipo,
          // Privado: es un comprobante bancario, no lo cachea ningún proxy.
          'Cache-Control': 'private, max-age=3600',
        },
      })
    } catch { /* probamos el próximo directorio */ }
  }
  return new Response('imagen no encontrada en disco', { status: 404 })
}
