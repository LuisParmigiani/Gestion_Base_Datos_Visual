# Sesión 8 — Se perdieron 7 h de cómputo y por qué no fue culpa del código

> ⛔ **DOS COSAS DE ESTE ARCHIVO SON FALSAS.** Corregidas en `sesion-09-colapso-alpha.md`
> (2026-08-09), leer eso antes que esto:
>
> 1. **No fue SIGHUP.** La corrida siguiente se lanzó con `nohup` + `disown` y murió en el
>    **mismo paso 162**. La causa es el ejemplo del índice 162 del dataset
>    (`ia/comprobantes/033.jpeg`, ~3078 tokens de imagen), reproducido en aislamiento.
> 2. **No guardar el estado del optimizador NO cuesta "un transitorio de unos pasos":**
>    destruyó 5 h de entrenamiento. Reanudar con Adam en cero llevó la loss de 7,9 a 31 en 25
>    pasos y, como cada paso pisa el checkpoint, se perdieron los pesos buenos. Ya está
>    arreglado, pero la decisión de esta sesión estaba mal tomada.

**2026-08-08.** La corrida de `lora_v2` lanzada el 7 a la tarde murió en el paso 162 de 335,
después de ~7 h, **sin dejar un solo peso en disco**. Esta sesión diagnostica por qué y hace
que no pueda volver a pasar.

---

## El diagnóstico: no fue un error del script

El log terminaba en el paso 162 y lo único que había después era un `UserWarning` de
`resource_tracker` sobre un semáforo. **Ningún traceback.** Esa es la firma de un proceso
*matado*, no de una excepción: si hubiera reventado el código, Python habría impreso la pila.

Cuatro comprobaciones, todas en contra de las hipótesis fáciles:

| Qué se miró | Comando | Resultado |
|---|---|---|
| ¿Murió el proceso o el sistema? | `pmset -g log \| grep caffeinate` | `PID 32417(caffeinate) ClientDied` a las **23:16:09** — el mismo segundo en que corta el log |
| ¿Se reinició la Mac? | `last reboot` / `uptime` | No. Último boot 3-ago 18:45, 4 días arriba |
| ¿Se quedó sin memoria? | `ls /Library/Logs/DiagnosticReports/*Jetsam*` | **Ningún JetsamEvent a esa hora.** El más cercano es del 8-ago 07:04, 8 h después |
| ¿Segfault? | crash reports de `python` | Ninguno |

`caffeinate`, `python` y `tee` murieron **juntos, en el mismo instante**, sin traceback y sin
que el sistema registrara nada. Eso es **SIGHUP: se cerró la terminal.** No se puede probar al
100% —SIGHUP no deja registro— pero es la única hipótesis consistente con las cuatro.

**Por qué se perdió todo:** `save_adapter()` estaba *después* del loop. Sobrevivió únicamente
`curva_loss.csv`, porque tenía `f.flush()` por paso. Los pesos, no.

> **La lección, más general que este bug:** lo que no se escribe a disco periódicamente no
> existe. `curva_loss.csv` sobrevivió porque alguien ya había pensado en el Ctrl-C; los pesos
> —lo caro— no tenían la misma protección.

## ⛔ Corrección a lo que se dijo en esta misma sesión

Al mirar las últimas 40 líneas del log se afirmó que **"la loss está planchada en ~8,1 desde
el paso 125"** y que eso olía al colapso de `lora_v1`. **Era falso.** Al medirlo contra el CSV
en vez de a ojo:

| | últimos 40 pasos vs los 40 previos | pendiente |
|---|---|---|
| **v2 (muerta en el 162)** | **bajó 0,307** | **−0,243** |
| v1 (la que colapsó) | bajó 0,013 | +0,003 |

Lo de v1 —3 milésimas en 40 pasos, del 140 al 300— *eso* es una meseta. v2 seguía bajando bien
cuando la mataron. **La corrida valía la pena repetirla tal cual, y se repitió.**

Y un recordatorio que sale del mismo cuadro: v1 en el paso 162 iba en **6,99**, más *bajo* que
los **8,12** de v2, y v1 es la rota. **La loss absoluta entre dos corridas no compara nada** —
v1 bajaba escupiendo comillas.

## El cambio en `ia/entrenar.py`

`mlx-vlm 0.1.15` no tiene `steps_per_save` ni resume: existen solo en la rama `main` de la
librería, que reabre los 4 bugs ya esquivados (ver sesión 4). Se hizo a mano.

| | Antes | Ahora |
|---|---|---|
| Guardado | 1 vez, al final del loop | **cada paso** (`--cada N` para espaciarlo) |
| Escritura | directa sobre el archivo | temporal + `os.replace` — **atómica** |
| Estado | nada | `estado.json`: paso, loss, hiperparámetros, hora |
| Reanudar | imposible | `--continuar` desde el último paso guardado |
| Ctrl-C | perdía el paso en curso | guarda y dice el comando para reanudar |

### ⛔ El costo del guardado: un número mal medido y su corrección

Durante la sesión se afirmó que guardar costaba **0,19 s** ("el 0,3 % del paso"). **Era falso.**
Ese número salía de cronometrar un `cp` de un archivo de 161 MB ya existente — o sea, solo
disco. El guardado real tardó **~99 s**.

La causa: `mx.save_safetensors` **fuerza la evaluación del grafo perezoso de MLX**. `loss.item()`
evalúa la loss, pero **no** el update de los pesos, que queda pendiente. El `save` es lo primero
que necesita esos valores materializados, así que paga el cómputo.

**Pero no es trabajo agregado, es trabajo mudado de lugar.** Sin guardar, ese mismo cómputo se
forzaba dentro del cronómetro del paso siguiente. La prueba está en la corrida muerta: la suma
de su columna `segundos` da **6,58 h** y el reloj de pared de 16:38 a 23:13 da **6,58 h** —
cero horas sin contabilizar. Todo el tiempo estaba dentro de los pasos.

| | s/paso (cronómetro) | s/guardado | **wall real** |
|---|---|---|---|
| Corrida muerta, sin guardar nunca | 146,2 | — | **146,2** |
| Corrida v2b, guardando cada paso | ~26 | ~60 | **85,8** (medido sobre 6 pasos) |

La corrida que guarda va **41 % más rápido** que la que no guardaba. La comparación no es limpia
—el 7-ago la máquina tenía OBS y CapCut encima— así que **el 41 % no se le atribuye al
guardado**. Pero pone un techo duro: si el `save` agregara trabajo real, el total no podría
estar por debajo del baseline. **`--cada 1` es correcto y no hay razón para espaciarlo.**

**La lección metodológica:** en MLX, cronometrar cualquier cosa exige preguntarse qué se
evaluó de verdad. El código ya tenía un comentario sobre esto para la loss y aun así el
guardado se midió mal.

Tres decisiones de diseño que conviene no revertir sin leer esto:

1. **Los pesos se escriben ANTES que el `estado.json`.** Si lo matan entre las dos escrituras,
   el estado apunta a un paso más viejo y al reanudar se repite un paso. Al revés se saltearía
   un paso en silencio. Se eligió el error barato.
2. **Se comparan las claves antes de cargar.** `load_weights(..., strict=False)` es
   obligatorio (el checkpoint tiene solo los params entrenables, no el modelo entero) y por eso
   mismo **no avisa si los nombres no coinciden**: cargaría cero tensores y el entrenamiento
   seguiría desde pesos random *sin un solo error*, tirando otras 12 h. El guardia es explícito.
3. **El estado del optimizador NO se guarda** (`ponytail:` en el código). Son los dos momentos
   de Adam sobre 40 M de params: triplicar peso y tiempo de cada guardado. `mlx-lm` tampoco lo
   hace. El costo es un transitorio de unos pasos al reanudar — **medido: la loss saltó de 36 a
   78** en el smoke test. Si algún día se reanuda seguido y ese salto ensucia la curva del
   informe, ahí sí conviene guardarlo.

## Qué se verificó, y con qué

**Mecánica, con un módulo chico** (sin cargar los 7B): las claves entrenables excluyen lo
congelado; `os.replace` no deja temporales; **`load_weights(strict=False)` carga de verdad**
(0,0102 → 7,0000, o sea que no es un no-op silencioso); un checkpoint de otro rank se detecta;
un `.tmp` corrupto no toca el checkpoint bueno.

**Smoke test 1** (`--iteraciones 3`, modelo real): los 3 pasos con `✓`, `adapters.safetensors`
escrito **antes del paso 1** (o sea que un crash temprano ya deja un adapter válido),
`estado.json` completo, `.tmp` limpio al terminar.

**Smoke test 2** (`--continuar --iteraciones 5`): imprimió `continuando desde epoch 0, paso 4`,
corrió **solo** los pasos 4 y 5, la curva quedó con las 5 filas (no pisó las 3 viejas) y el md5
del adapter cambió. Esto es lo que prueba que las claves LoRA del Qwen2-VL **real** coinciden
al reanudar — lo único que el módulo chico no podía cubrir.

## La otra mitad: el comando

El código solo limita el daño a un paso. Lo que evita el kill es cómo se lanza:

```bash
nohup caffeinate -dims ia/.venv/bin/python ia/entrenar.py ... \
  > ia/checkpoints/entrenamiento_lora_v2b.log 2>&1 < /dev/null &
disown
```

- `nohup` → SIGHUP ignorado
- `< /dev/null` → stdin desatado, no muere si la terminal desaparece
- `disown` → zsh no le manda HUP a sus jobs al salir
- **se fue el `| tee`**: se mira con `tail -f`, y **Ctrl-C sobre el `tail` ya no mata el
  entrenamiento**. Esa era la trampa

`caffeinate -s` no impide dormir con la tapa cerrada a batería: **enchufada**.

## Lo que quedó abierto

- La corrida de 335 pasos quedó lanzada de 0 el 8-ago 09:28, log en
  `ia/checkpoints/entrenamiento_lora_v2b.log`. Cadencia medida sobre los primeros pasos:
  **85,8 s de reloj por paso → ~8 h**, contra las 13,6 h que proyectaba la corrida del 7.
  Son 6 muestras de los primeros ejemplos del dataset: **la proyección puede moverse**, y no
  hay que leerla como promesa. El cronómetro que imprime el script (~26 s) **no incluye el
  guardado**: para el tiempo real hay que mirar el reloj, no esa columna.
- **`ia/checkpoints/lora_v1/` sigue en disco** (roto, con su `adapters.safetensors`). No se
  tocó: es la evidencia de la meseta que se usó para el cuadro de arriba.
- La curva de la corrida muerta se preservó en
  `ia/checkpoints/lora_v2/curva_muerta_paso162.csv` — relanzar sin `--continuar` la habría
  pisado, porque la curva se abre en modo `w`.
