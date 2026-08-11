<!-- Parte de la bitácora. Se lee SOLO si `.claude/BITACORA.md` manda a leerlo. -->

## 2026-08-05 · Sesión 1 — Diseño

**Estado:** F0 sin empezar. Escritos `README.md`, `CLAUDE.md`, `PLAN.md`.

### Análisis de `TRANSFERENCIAS.xlsx`

> ⚠️ **Cinco de estos números resultaron falsos.** Se midieron de nuevo contra el archivo el
> 2026-08-06 y están corregidos arriba: 2843 filas con contenido (no 3364), 21 pares
> repetidos (no 20), 1 importe ambiguo (no 29), 84 COELSA (no 95), y las fechas son `Date`
> (no seriales). **Se deja lo original a propósito**, para que se vea de dónde salió el error.

3364 filas, 3 hojas = 3 cuentas (`SUCESION` 1310, `QUIQUE` 1832, `MARIELA` 219).
Rango 2026-02-23 → 2026-08-05. Columnas `FECHA | NRO TRANSACCION | DESCRIPCION | IMPORTE | SALDO`.

| Hallazgo | Dato |
|---|---|
| Formatos de número mezclados | 2481 AR (`$ 368.500,00`) / 332 US (`$ 16,000.00`) / 29 ambiguos |
| `SALDO` | Descartado por decisión: es el saldo de la cuenta, información del banco |
| ID COELSA presente | 95 de 3364 (~3%), patrón `TRANSF:` o `CREDIN:` + `[A-Z0-9]{20,24}` |
| CUIT parseable | 64% (QUIQUE) a 93% (SUCESION) |
| Nombres | Truncados a 8-16 caracteres — inservibles |
| `NRO TRANSACCION` | 1309 presentes / 1286 distintos → no es clave única |
| Filas 100% idénticas | 20 (11 SUCESION, ~7 QUIQUE, 2 MARIELA) |
| Filas vacías | 517 en QUIQUE |
| Egresos | En negativo (Movistar, AFIP, IIBB, AGUAS, EPE, tasas) |
| Fechas | Seriales de Excel (`46080.0` → `2026-02-27`), epoch 1899-12-30 |
| Columna `F` | Anotaciones personales ajenas al proyecto — **se ignora** |

### Prueba de cruce con un comprobante real

`Macro.jpeg`: PEÑA STELLA MARIS → $250.000, 02/06/2026 21:46, CUIT emisor 27062108679,
COELSA `7L8GYKNX0L3RK0XK2MPRZ5`. Receptor: "Mercado Libre Srl - CV ARS 4603".

Buscado por CUIT, por COELSA y por importe: **0 coincidencias en las 3364 filas.**

No es fraude. Los 52 comprobantes reales son de otra fuente y otro período. De acá sale la
decisión más importante del diseño: **el estado "no verificable"**, distinto de "sospechoso".

### Decisiones tomadas

| Decisión | Motivo |
|---|---|
| Conciliación antes que IA | La IA solo evita tipear. Si falla, no debe llevarse el proyecto |
| Fine-tuning sí o sí | Requisito de la materia. Pero se mide zero-shot antes, como grupo de control |
| Solo conciliación, sin forense de imagen | El extracto ya dice la verdad; el forense agrega falsos positivos |
| Deudas al final (F12) | La deuda vive en otra API. La v1 no manda información afuera |
| Seis estados, no dos | "No aparece" ≠ "es falso" |
| PostgreSQL | Preferencia explícita. SQLite descartado |
| Motor probado con fixtures fabricadas | Los comprobantes reales no cruzan con este extracto |
| Verdad de referencia por corrección | 30 comprobantes, corregir zero-shot en vez de tipear |
| `SALDO` fuera del modelo | Información del banco, no del proyecto. Las 29 filas con importe ambiguo se marcan para revisión manual en vez de resolverse con la cadena de saldos |
| Confirmación previa a cada paso | Regla 1 de `CLAUDE.md`. Explicar antes de tocar nada |

### F0 — Preparado el terreno

- `viejo.` → `viejo` (el punto final rompía rutas)
- `.gitignore` en la raíz. **Sin `git init`**: el repo lo crea el usuario aparte, sobre un
  proyecto ya existente. `viejo/` va ignorado entero
- PostgreSQL 18.4 (Postgres.app), base `conciliador`,
  `postgresql://luisparmigiani@localhost:5432/conciliador`. Descartado Docker: su VM se come
  2 GB permanentes y en F9 el fine-tuning necesita 12-14 de los 24
- `web/` con Next.js 16.3.0, React 19.2.8, Tailwind 4.3.3, TypeScript 5.9.3. En subcarpeta
  porque `create-next-app` pisa el `README.md` y el `.gitignore` de la raíz. Flags:
  `--disable-git --empty`. Dependencias: `pg`, `exceljs`, `@types/pg`
- Verificado: `pnpm dev` responde 200 en localhost:3000
- **Regla nueva: siempre `pnpm`**, nunca `npm` ni `yarn`
- **Next 16 rompe compatibilidad con lo aprendido por el modelo.** `web/AGENTS.md` lo avisa y
  `next dev` lo regenera solo. Se lee `web/node_modules/next/dist/docs/` antes de escribir

### Abierto

- Tolerancia de fecha en ±1 día hábil, sin confirmar contra casos reales
- Falta decidir si las filas duplicadas se descartan solas o se marcan para revisar
- La API de deudas (F12) sigue sin definirse
- Sin confirmar si `mlx-vlm` soporta Qwen2.5-VL — se evalúa en F7
