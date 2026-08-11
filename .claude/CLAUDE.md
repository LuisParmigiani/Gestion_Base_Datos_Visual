# Reglas del proyecto

Claude carga este archivo al inicio de cada sesión. Son reglas, no sugerencias.

> **Al empezar cualquier sesión, leer `BITACORA.md` antes de hacer nada — y solo ese.** Arriba
> de todo tiene el bloque **ESTADO ACTUAL**: en qué fase estamos, qué quedó propuesto sin
> confirmar, y qué hay que verificar antes de seguir (entre otras cosas, que Postgres esté
> levantado — no arranca solo). Si el usuario escribe "continuemos", la respuesta sale de ahí.
>
> **No leer `.claude/bitacora/*.md` de entrada.** Son el relato de cada sesión y suman más de
> mil líneas. Se abre uno **solo cuando el ESTADO ACTUAL o el índice mandan a abrirlo**, o
> cuando se va a tocar el código del que ese archivo habla.

---

## 0. Las cuatro reglas que mandan sobre todas las demás

1. **Antes de cada paso, explicar qué se va a hacer y esperar confirmación.** Ver la sección 3.
2. **Los datos bancarios reales no salen de esta máquina.** Ni a una API, ni a un artifact,
   ni a un gist, ni a un servicio de scraping, ni a un modelo en la nube. Nunca.
3. **El extracto del banco es la única fuente de verdad.** Ante cualquier duda entre lo que
   dice el comprobante y lo que dice el extracto, gana el extracto.
4. **"No lo encontré" nunca se reporta como "es falso".** Ver los seis estados en el README.

---

## 1. Skills obligatorias

### `ponytail` — SIEMPRE, en todo el código

Activa en cada respuesta que produzca código. No hay excepción, no hay "esto es chico".
Antes de escribir algo, la escalera: ¿hace falta que exista? → ¿lo hace la stdlib? → ¿lo hace
el lenguaje/la plataforma? → ¿lo hace una dependencia que ya está? → ¿entra en una línea?

Los atajos deliberados se marcan con un comentario `ponytail:` que nombra el techo y cómo
subirlo:

```python
# ponytail: parseo de fecha asume el formato del Macro, generalizar si aparece otro banco
```

Al cerrar cada fase se corre `/ponytail-review` sobre el diff. Al cerrar cada bloque,
`/ponytail-audit` sobre el repo.

**Precedencia:** ponytail manda sobre *qué código se escribe*. Superpowers manda sobre
*cómo se llega a escribirlo*. No se contradicen: ponytail no es excusa para saltear tests,
y TDD no es excusa para inventar abstracciones.

### `context7` — SIEMPRE, antes de escribir contra cualquier librería

`resolve-library-id` y después `query-docs`, antes de la primera línea contra `mlx-vlm`,
`exceljs`, `pg`, Next.js, FastAPI, `transformers` o cualquier otra.

Aplica **aunque creas que te acordás de la API.** `mlx-vlm` en particular cambia de firma
entre versiones menores, y el proyecto anterior murió justamente por asumir un formato de
dataset que la librería no aceptaba. No se repite ese error.

### `superpowers:test-driven-development` — en el motor de conciliación

El motor es lógica pura con entradas y salidas conocidas: es el caso ideal de TDD y el
componente donde un error silencioso acusa a un cliente honesto. Test primero, siempre.

No aplica a la interfaz ni a los scripts de exploración.

### `superpowers:verification-before-completion` — antes de decir que algo anda

Nunca "listo", "funciona" o "arreglado" sin haber corrido el comando y pegado la salida.
Si los tests fallan, se dice que fallan.

### `superpowers:systematic-debugging` — al segundo intento fallido

Si el mismo error sobrevive a dos intentos de arreglo, se frena y se diagnostica en vez de
seguir probando. Complementa `debugging-solucionador` (skill propia, en español).

### Por área de trabajo

| Cuándo | Skill |
|---|---|
| Código Python (IA, entrenamiento) | `python-developer-senior` |
| Esquema, migraciones, queries | `postgresql-query-expert` |
| Antes de cerrar una fase | `code-simplifier` o `/ponytail-review` |
| Diagnóstico de tipos | `pyright-lsp` (Python), `typescript-lsp` (TS) |
| Pantallas de la interfaz | `ui-ux-pro-max` — solo para claridad y legibilidad |
| Modelos, MLX, cuantización | `huggingface-skills` — **solo consulta y descarga local** |
| Trabas y sesiones enredadas | `debugging-solucionador` |

---

## 2. Prohibido

### Datos — prohibición dura

- ❌ Mandar comprobantes, extractos, CUITs, nombres o montos reales a **cualquier** servicio
  externo. Incluye Firecrawl, Exa, Tavily, Apify, Bright Data, artifacts publicados, gists,
  pastebins y APIs de modelos en la nube.
- ❌ Commitear a git: `TRANSFERENCIAS.xlsx`, `viejo./comprobantesReales/`, cualquier imagen de
  comprobante real, cualquier dump de la base. Van al `.gitignore` en la Fase 0.
- ❌ Usar datos reales en tests. Los tests usan las fixtures generadas de la Fase 3.

### IA — prohibición dura

- ❌ **Usar la IA para generar la verdad de referencia.** Mediría el modelo contra sí mismo y
  el número no significaría nada. La corrección humana del zero-shot (Fase 6) es corrección,
  no generación: cada campo lo confirma una persona.
- ❌ APIs de modelos pagas (OpenAI, Gemini, Claude API) para extraer comprobantes. El proyecto
  es 100% local por costo y por privacidad.
- ❌ Entrenar en la nube (HF Jobs, Colab, SageMaker). El entrenamiento corre en el M4 Pro.
- ❌ Reportar métricas sin decir sobre cuántos comprobantes se midieron.

### Alcance — no se construye

- ❌ Login, usuarios, roles, permisos. Una persona, máquina local.
- ❌ Deploy: Vercel, Cloudflare, Supabase cloud, Firebase, Docker para producción.
- ❌ Análisis forense de imágenes. Decidido fuera de alcance.
- ❌ Módulo de deudas antes de la Fase 12. La deuda vive en otra API.
- ❌ Mandar información hacia afuera. La v1 solo compara y opina.

### Código

- ❌ **`npm` o `yarn`. Siempre `pnpm`.** Sin excepción: instalar, correr scripts, agregar
  dependencias, crear el proyecto. Si aparece un comando con `npm` en una documentación, se
  traduce a `pnpm` antes de correrlo. Nunca se genera un `package-lock.json` ni un `yarn.lock`;
  el único lockfile del repo es `pnpm-lock.yaml`.
- ❌ Dependencia nueva sin justificar por qué la stdlib o algo ya instalado no alcanza.
- ❌ ORM, capa de repositorios, inyección de dependencias, fábricas. SQL plano con `pg`.
- ❌ Abstracción con una sola implementación. Se inlinea hasta que exista la segunda.
- ❌ SQLite. Descartado a propósito: se quiere algo robusto.
- ❌ `float` para plata. Los importes van en `NUMERIC` de Postgres.
- ❌ Adivinar un importe ambiguo. Hay dos formatos mezclados en la misma columna y el error es
  silencioso: la fila dudosa se marca `requiere_revision`, no se resuelve por corazonada.
- ❌ Guardar, mostrar o razonar sobre la columna `SALDO`. Es información del banco, no del
  proyecto.
- ❌ Datos mock presentados como reales, o funciones que devuelven valores fijos simulando
  que andan.

### Plugins que no se tocan en este proyecto

Stripe, Shopify, Zoom, Slack, Atlassian, Linear, LegalZoom, Postman, Playwright,
chrome-devtools, gsap-scrolltrigger, aframe-webxr, core-3d-animation,
animated-component-libraries, modern-web-design, firecrawl, exa, brightdata, apify,
data-engineering, mcp-server-dev, ralph-loop.

Es una herramienta interna de conciliación contable. No lleva animaciones, ni 3D, ni scraping,
ni pasarela de pagos.

### Archivos

- ❌ Modificar o borrar `viejo./`. Es referencia histórica de solo lectura.
- ❌ Modificar `README.md` sin pedirlo explícitamente.
- ❌ Crear archivos de documentación nuevos porque sí. Son cuatro: `README.md`, `CLAUDE.md`,
  `PLAN.md`, `BITACORA.md`. Alcanzan.
- ✅ Excepción única: `.claude/bitacora/`, que es `BITACORA.md` partido en dos niveles (ver la
  sección 4). Ahí sí se crea un archivo por sesión, y **ningún otro documento suelto**.
- ⚠️ Excepción: `web/AGENTS.md` y `web/CLAUDE.md` los genera `next dev` solo, en cada arranque.
  **No se borran.** Avisan que Next.js 16 rompe compatibilidad con lo que el modelo tiene
  aprendido. Antes de escribir cualquier código de Next.js o React en este proyecto, se lee
  `web/node_modules/next/dist/docs/` — no se escribe de memoria. Versiones instaladas:
  **Next.js 16.3.0, React 19.2.8, Tailwind 4.3.3**, las tres más nuevas que el corte de
  conocimiento del modelo.

---

## 3. La confirmación previa — regla dura

**Antes de empezar cualquier paso, explicar qué se va a hacer y esperar el visto bueno.**
No se toca un archivo hasta que llegue.

La explicación previa dice, corto:

1. **Qué archivos** se crean o se modifican
2. **Qué comandos** se van a correr, sobre todo los que instalan, borran o cambian el sistema
3. **Qué queda funcionando** al terminar
4. **Qué decisión** se está tomando por default, si hay alguna

Después se espera. Un "dale", "sí" o "arrancá" alcanza. Silencio no alcanza, y "parece bien"
tampoco: se pregunta de nuevo.

**Aplica a cada paso, no a cada fase.** Una fase puede tener varios pasos y cada uno lleva su
explicación. Ante la duda de si algo es un paso o parte del anterior, se pregunta.

**No aplica a:** leer archivos, buscar, correr tests que ya existen, ni consultar
documentación. Eso no cambia nada y no necesita permiso.

**Si en el medio de un paso aparece algo que no estaba en la explicación** — un archivo que hay
que tocar y no se había mencionado, una dependencia que falta, una decisión que no estaba
prevista — se frena y se explica antes de seguir. La confirmación cubre lo que se explicó, no
lo que se descubrió después.

---

## 4. Cómo se trabaja

**Idioma:** español, en código, comentarios, commits e interfaz. Los nombres de columna del
extracto se conservan como vienen (`NRO TRANSACCION`, `IMPORTE`, `SALDO`).

**Una fase por vez.** No se empieza la siguiente sin cumplir el criterio de listo de la
anterior. El criterio está escrito en `PLAN.md` y es verificable con un comando, no con una
opinión.

**Bitácora, en dos niveles.** Al terminar una fase o tomar una decisión que no estaba en el
plan se anota: qué se hizo, qué se decidió, qué quedó abierto. El proyecto es multi-sesión;
sin bitácora cada sesión arranca de cero. El intento anterior ya tropezó con esto.

| Archivo | Qué lleva | Cuándo se lee |
|---|---|---|
| `BITACORA.md` | ESTADO ACTUAL, mapa del código, entorno, deudas, índice | **Siempre, al empezar** |
| `.claude/bitacora/sesion-NN-tema.md` | El relato completo de una sesión | Solo si el índice o el estado mandan |

Al cerrar una sesión, su relato se escribe en `.claude/bitacora/sesion-NN-tema.md` y en
`BITACORA.md` quedan **dos cosas y nada más**: lo que cambió en el ESTADO ACTUAL, y una línea
en el índice. Lo que ya está contado en un archivo de sesión no se repite arriba: se enlaza.

**El techo son ~250 líneas en `BITACORA.md`.** Si lo pasa, algo que debía mudarse se quedó, y
la próxima sesión va a gastar la mitad del contexto leyendo historia en vez de trabajando.
Los archivos de sesión no se editan una vez cerrados: si algo de ahí resultó falso, se corrige
**donde se descubrió** y se deja una marca ⛔ en el original apuntando a la corrección.

**Modo asesor, no complaciente.** Si una decisión parece equivocada, se dice antes de
ejecutarla, con el motivo y la alternativa. Si igual se confirma, se ejecuta completo y sin
volver sobre el tema. Lo que no se hace es decir que sí y construir otra cosa.

**Frente a un número raro, se verifica.** Este proyecto ya dio tres sorpresas al mirar los
datos de verdad: dos formatos de número mezclados, el ID COELSA presente solo en el 3% de las
filas, y un comprobante legítimo ausente del extracto. Las suposiciones sobre los datos se
confirman leyendo los datos.
