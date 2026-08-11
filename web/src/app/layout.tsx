import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'

export const metadata: Metadata = {
  title: 'Conciliador de comprobantes',
  description: 'Verifica que las transferencias declaradas entraron al banco',
}

const PANTALLAS = [
  { href: '/', texto: 'Tablero' },
  { href: '/probar', texto: 'Probar comprobante' },
  { href: '/resolver', texto: 'Resolver' },
  { href: '/revisar', texto: 'Revisar extracción' },
  { href: '/corridas', texto: 'Comparar corridas' },
  { href: '/encontrar', texto: 'Encontrados' },
  { href: '/comprobante', texto: 'Cargar comprobante' },
  { href: '/extracto', texto: 'Subir extracto' },
  { href: '/cbu', texto: 'CBU propios' },
]

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="es">
      <body className="bg-stone-50 text-stone-900">
        <nav className="border-b border-stone-300 bg-white">
          <div className="mx-auto flex max-w-6xl flex-wrap gap-6 px-6 py-4 text-sm">
            {PANTALLAS.map((p) => (
              <Link key={p.href} href={p.href} className="hover:underline">
                {p.texto}
              </Link>
            ))}
          </div>
        </nav>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  )
}
