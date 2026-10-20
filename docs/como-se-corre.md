# Cómo se corre

> Para saber más. Los comandos completos de las dos aplicaciones. La guía de uso simple está en el [README](../README.md).

# Stack

| Capa | Elección | Por qué |
|---|---|---|
| Base de datos | **PostgreSQL 18** (local) | Robusto. SQLite descartado a propósito |
| Acceso a datos | `pg` + SQL plano | Sin ORM. 9 tablas no justifican una capa más |
| Web | **Next.js 16 · React 19 · TypeScript 5.9** | Un proceso sirve interfaz + API + subida de archivos |
| Estilos | **Tailwind 4** | |
| Tests | `node --test` | Sin framework. **200 en verde** |
| Lectura de Excel | `exceljs` | El import es del lado web; no hace falta pasar por Python |
| Extracción IA | **Python + MLX + Qwen2-VL-7B 4-bit** | Apple Silicon, sin costo por token, sin mandar datos afuera |
| Entrenamiento | **LoRA** vía `mlx-vlm` 0.1.15 | Adapta el 0,53% de los pesos |
| Gestor de paquetes | **`pnpm`**, nunca `npm` ni `yarn` | |

**MLX solo funciona en Apple Silicon:** no hay servidor Linux que valga, y además los datos
bancarios reales no salen de la máquina.

---

# Cómo se corre

Requiere PostgreSQL 18 levantado (Postgres.app **no arranca solo**) y `pnpm`.

```bash
nc -z localhost 5432 && echo arriba || open -a Postgres

cd web
pnpm importar ../TRANSFERENCIAS.xlsx    # Excel → Postgres, sin duplicar. Reimportar es seguro
pnpm dev                                # localhost:3000
pnpm test                               # la suite completa

# la IA, siempre local
ia/.venv/bin/python ia/extraer.py ia/comprobantes/*.jpeg > salida.jsonl
ia/.venv/bin/python ia/extraer.py --adaptador ia/checkpoints/lora_v4 imagen.jpeg
```

## Las nueve pantallas

| Pantalla | Qué hace |
|---|---|
| `/` | Tablero con los seis estados, filtro por estado y cuenta, y Recalcular |
| `/extracto` | Subir el Excel |
| `/comprobante` | Carga a mano de los 16 campos |
| `/probar` | Subir una foto y ver los 16 campos, **sin tocar la base**, con selector de adaptador |
| `/revisar` | **La corrección humana.** Imagen a la izquierda, 16 campos a la derecha, cuatro filtros y *Revisar N de corrido* |
| `/encontrar` | Asignación comprobante ↔ fila del extracto, con buscador y export a Excel con colores |
| `/resolver` | Los ambiguos del motor viejo |
| `/cbu` | Aprobar los CBU propios de a uno |
| `/corridas` | El historial de corridas del modelo |

**`/revisar` no deja guardar una forma imposible sin avisar:** si un CUIT no da 11 dígitos o un
CBU no da 22, se queda en la pantalla, dice cuál y ofrece *Guardar igual* — que es lo que
escribe `formato_aceptado_en`.

---


# El producto — `portal/`


```bash
nc -z localhost 5432 && echo arriba || open -a Postgres      # Postgres NO arranca solo

ia/.venv/bin/uvicorn portal.app:app --reload --port 8000     # cliente en / · dueño en /admin
ia/.venv/bin/python -m portal.sembrar                        # clientes inventados
ia/.venv/bin/python -m portal.verificar_saldos               # el saldo contra el libro
ia/.venv/bin/python -m portal.importar <archivo.xlsx> [cuenta]
ia/.venv/bin/python -m portal.lote [--incluir-50]            # el lote por consola

PORTAL_DATABASE_URL="postgresql+psycopg://luisparmigiani@localhost:5432/portal_test" \
  ia/.venv/bin/python -m unittest discover portal/tests      # 94 tests
```

⚠️ **`sembrar.py --reiniciar` hace `drop_all`.** Se niega a correr si hay comprobantes
subidos, porque una vez se llevó puesto el de una persona: el archivo quedó en disco y su
fila desapareció. Para cambiar el esquema **se usa `ALTER TABLE`**, no se recrea la base.

⚠️ **No hay Alembic.** Las tablas se crean con `create_all()` y los cambios se hacen a mano
con `ALTER TABLE`. Alcanza mientras los datos sean inventados; el día que haya datos reales
de clientes, hace falta.

