import { Pool } from 'pg'

// ponytail: un Pool de módulo, sin wrapper ni capa de repositorios. El SQL se
// escribe donde se usa. Si `next dev` empieza a dejar pools colgados entre
// recargas, cachearlo en globalThis; hasta que pase, no.
export const db = new Pool({ connectionString: process.env.DATABASE_URL })
