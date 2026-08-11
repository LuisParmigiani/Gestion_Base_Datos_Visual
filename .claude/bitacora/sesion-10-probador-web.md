# Sesión 10 — La calibración cerró, y una pantalla para mostrar algo

**2026-08-10.** Se cerró la calibración de alpha de la sesión 9, se lanzó la corrida larga
(`lora_v3`) y se construyó `/probar`: subir la foto de un comprobante y ver los 16 campos.

---

## 1. La calibración terminó y los dos alphas pasaron

| | `cal_0.1` | `cal_1.0` |
|---|---|---|
| Duración | 90,9 min | 84,2 min |
| Segundos por paso | 136,4 | 126,3 |
| Canarios (pasos 10/20/30/40) | **✓ ✓ ✓ ✓** | **✓ ✓ ✓ ✓** |
| Loss, promedio de los últimos 10 pasos | **5,3119** | **5,2692** |

Los ocho canarios dieron JSON válido. Ninguno de los dos alphas colapsó, que es exactamente
lo que `lora_v1` y `lora_v2` no lograban. **Primera confirmación en vivo del diagnóstico de la
sesión 9.**

### La loss no sirvió para elegir, y era previsible

Las dos curvas terminan a **0,8% una de otra**. Se separan solo en los primeros 5 pasos
(paso 2: 10,32 contra 7,91) y después convergen hasta ser indistinguibles.

Tiene sentido: **Adam normaliza la magnitud del gradiente**, así que multiplicar `alpha` por 10
multiplica por 10 el movimiento en el espacio de la *función*, pero el paso en el espacio de
los *pesos* lo fija el `lr`. La loss ve el segundo, no el primero.

> Es la misma lección de la sesión 9, en versión suave: **la loss no mide la capacidad que
> importa.** Allá no detectó un colapso total; acá no detecta una diferencia de escala de 10×.
> El canario sí ve las dos cosas, porque genera de verdad.

**Se eligió `alpha 0.1`** — el default de la librería y el lado seguro de la escala. No hay un
número que lo pruebe mejor que `1.0`; se eligió por criterio, y eso quedó dicho.

⚠️ **40 pasos no prueban que `1.0` sea seguro.** `v1` y `v2` colapsaron en corridas largas, no
en 40 pasos. Si `lora_v3` sale bien, la pregunta "¿`1.0` habría dado más?" sigue abierta y solo
la contesta otra corrida larga.

## 2. El swap no es un detalle de performance: es el factor dominante

Con Safari, VS Code y `next dev` abiertos, la calibración corrió a **136 s/paso**. Con la Mac
liberada, el mismo entrenamiento hace pasos de **17-26 s de cómputo**. Es un factor de ~6×.

**Al lanzar una corrida larga, cerrar todo es la optimización más grande disponible**, y no
cuesta nada. Chequear siempre con `sysctl vm.swapusage` antes de sacar conclusiones de un
cronómetro: un paso lento casi nunca es el modelo.

## 3. `--cada 1` es gratis — y el error de haber dicho lo contrario

⛔ **A mitad de esta sesión se anotó acá que guardar cada paso SÍ alargaba el entrenamiento, y
que `--cada 10` bajaría la corrida de 7,7 h a 2,8 h. Las dos cosas son FALSAS.** Se escribieron
mirando solo la diferencia entre los 25 s de la columna `segundos` y los 90 s de reloj, y
atribuyéndola al disco **sin leer el código ni medir el disco**.

**La medición que lo cierra:** escribir los 462 MB del checkpoint y sincronizarlo a disco toma
**0,34 s** (`dd` + `sync`, 2026-08-10). El disco no es el cuello, ni de lejos.

Los ~65 s son **cómputo real que el guardado fuerza**: `save_safetensors` evalúa el grafo
perezoso de MLX, o sea el update de los pesos, que `loss.item()` no evalúa. **Es trabajo mudado
de lugar, no agregado** — sin guardar se paga igual, dentro del paso siguiente. La cabecera de
`entrenar.py` ya lo explicaba y lo tenía medido: **85,8 s/paso guardando contra 146,2 s/paso
sin guardar.** Guardar en cada paso es más rápido, no más lento.

> **La lección, que es de método:** el archivo decía "está medido que no alarga" y se lo trató
> como sospechoso sin abrir el código que estaba al lado. Una discrepancia entre dos números
> observados no autoriza a inventar el mecanismo que la explica: primero se mide el mecanismo.
> El costo de esta equivocación habría sido matar una corrida sana para "optimizarla".

## 4. `/probar` — la pantalla para mostrar algo

Tres archivos:

```
web/src/app/probar/page.tsx        server component: lista los adaptadores que hay en disco
web/src/app/probar/formulario.tsx  'use client': subir, esperar, ver los 16 campos agrupados
web/src/app/acciones.ts            + probarComprobante(): la Server Action
web/src/app/layout.tsx             + el link en la nav
```

**Decisiones, con su motivo:**

- **No escribe en la base.** La imagen va a un `mkdtemp` y se borra en el `finally`. Los 51
  comprobantes revisados a mano son lo más caro que tiene el proyecto y una pantalla de demo
  no puede tener permiso para ensuciarlos.
- **Modelo base + prompt v3 por default, con selector de adaptador.** El selector lee
  `ia/checkpoints/` en cada carga, así que un LoRA aparece solo apenas exista — incluso a medio
  entrenar, porque `entrenar.py` escribe el adapter de forma atómica en cada paso.
- **El nombre del adaptador se valida** con `/^[\w.-]+$/`. Una Server Action se alcanza con un
  POST directo, no solo desde la pantalla, y ese string arma una ruta.
- **Timeout de 15 minutos.** Con un entrenamiento en paralelo la memoria se pelea y una lectura
  que suelta tarda 16 s puede irse a varios minutos.
- **Los tres disfraces de la ausencia** (`''`, `'N/A'`, `'null'`) se muestran como
  *"— no lo encontró —"*, nunca como valor.

## 5. Cómo se verificó, y por qué costó

`GET /probar` daba 200 y `tsc`/`eslint`/`pnpm test` (157) estaban limpios, pero eso **no prueba
que la acción corra Python**. La extensión de Chrome no estaba conectada, así que se intentó
por HTTP y ahí apareció la trampa:

> Un POST con el header `Next-Action` y otro con el campo `$ACTION_ID_<id>` **fallan los dos**.
> Sin JavaScript, React llama la acción con **un solo argumento**, así que la firma
> `(_previo, formData)` recibe `formData = undefined`. El error `Cannot read properties of
> undefined (reading 'get')` **era del curl, no del código.**

La verificación buena fue una ruta temporal (`api/probar-test/route.ts`) que llama
`probarComprobante(null, formData)` con la forma que le pasa `useActionState`. **Resultado:
HTTP 200 en 15,8 s con los 16 campos.** La ruta se borró apenas terminó.

⚠️ **Lo que quedó sin verificar:** el viaje por el navegador (`useActionState` → render). Es el
mismo patrón que ya usan `/extracto`, `/comprobante` y `/revisar`, pero no se lo vio funcionar
con los ojos. Abrir `localhost:3000/probar` y subir una foto lo cierra en 30 segundos.

## 6. El modelo devuelve el string `"null"`, y `oNulo` no lo atrapa

`oNulo` (en `importar-comprobantes.ts`) trata `''` y `'N/A'` como ausencia, **pero no `'null'`**.
El modelo devuelve las tres.

Medido sobre los 51 revisados, campos donde el modelo dijo `"null"` **y la verdad también está
vacía** — es decir, aciertos que hoy se cuentan como errores:

| Corrida | Dice `"null"` | De esos, la verdad es vacío |
|---|---|---|
| v1 | 8 | **4** |
| v2 | 11 | **4** |
| v3 | 16 | **5** |
| v4 | 58 | **7** |

**Es real pero chico y no cambia ninguna conclusión:** v1 pasaría de 532 a 536 (65,2% → 65,7%)
y v4 de 338 a 345 (41,4% → 42,3%). **El orden entre las corridas no se mueve y el "65% es el
mejor número honesto" sigue en pie.**

Además hay **3 filas de `comprobante`** con el texto `'null'`/`'N/A'` guardado como si fuera un
valor (2 en `coelsa_id`, 1 en `referencia`).

**No se tocó `oNulo`.** Cambiarlo mueve todos los números publicados del proyecto, y eso se
decide a propósito, no de paso. En `/probar` se resolvió solo del lado de la pantalla.

## 7. Correcciones a lo que decía la bitácora

- ⛔ **"5 corridas"** → son **6**: entró `lora_v2` el 2026-08-09.
- ⛔ **"`--cada 1` no alarga el entrenamiento"** → sí alarga. Ver la sección 3.
- Los logs `cal_0.1.log` y `cal_1.0.log` ya están a salvo en `ia/checkpoints/`. El
  `cal_0.1.log` que había era el parcial del paso 24; ahora está completo.
