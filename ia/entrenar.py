"""Fine-tuning LoRA de Qwen2-VL sobre el dataset sintético (F9). Local.

    ia/.venv/bin/python ia/entrenar.py --iteraciones 10      # smoke test
    ia/.venv/bin/python ia/entrenar.py                       # el dataset entero
    ia/.venv/bin/python ia/entrenar.py --continuar --salida ia/checkpoints/lora_v2

Es el `main()` de `mlx_vlm/lora.py` 0.1.15 con cuatro cambios, todos necesarios:

  1. EL PARCHE DEL IMAGE PROCESSOR. `load()` arma el processor "fast", que solo
     devuelve tensores de PyTorch. Sin esto revienta con "Only returning PyTorch
     tensors is currently supported" — el mismo error que ya tenía extraer.py.
     `lora.py` no lo aplica, así que `python -m mlx_vlm.lora` no sirve tal cual.
  2. La curva de loss a un CSV. Es material del informe: una curva que no baja
     dice que los hiperparámetros están mal.
  3. Sin el flag --apply-chat-template. En 0.1.15 está declarado
     `action="store_false"`, o sea que el default YA es aplicarlo y pasarlo lo
     DESACTIVA. Acá se aplica siempre, que es lo correcto.
  4. CHECKPOINT EN CADA PASO, y --continuar para reanudar. `lora.py` guarda una
     sola vez, al final del loop: la corrida de lora_v2 murió en el paso 162 de
     335 y se perdieron 7 h de cómputo sin dejar un solo peso en disco. 0.1.15 no
     tiene ni `steps_per_save` ni resume (existen solo en la rama main de la
     librería, que trae los otros bugs de vuelta), así que va a mano.

     OJO con cronometrar el guardado: no es disco, son ~99 s. `save_safetensors`
     fuerza la evaluación del grafo perezoso de MLX — el update de los pesos, que
     `loss.item()` NO evalúa. Pero no es trabajo agregado, es trabajo mudado de
     lugar: sin guardar, ese mismo cómputo se forzaba dentro del paso siguiente.
     Medido: 85,8 s de reloj por paso (paso + guardado) contra 146,2 s/paso de la
     corrida que no guardaba nunca. Guardar en cada paso no cuesta tiempo.

El dataset lo produce ia/generar.py. `content` va como string plano: el wrapper
de mlx-vlm reconstruye los mensajes y pone el token de imagen él solo. Ver la
sesión 4 de BITACORA.md.
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MODELO = "mlx-community/Qwen2-VL-7B-Instruct-4bit"


def main() -> None:
    p = argparse.ArgumentParser(description="Fine-tuning LoRA local de Qwen2-VL.")
    p.add_argument("--dataset", type=Path, default=AQUI / "sinteticos" / "train.jsonl",
                   help="el .jsonl de entrenamiento. Tiene que ser un ARCHIVO, no un "
                        "directorio: apuntar al directorio se lleva todos los .jsonl "
                        "que haya adentro, incluido el de los apartados")
    p.add_argument("--iteraciones", type=int, default=0,
                   help="steps por epoch. 0 = el dataset entero")
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--alpha", type=float, default=0.1,
                   help="ESCALA DIRECTA del update LoRA — NO es el alpha de PEFT. mlx-vlm "
                        "hace `y + alpha * update` SIN dividir por rank (LoRaLayer.__call__ "
                        "en trainer/utils.py), así que --alpha 32 no da escala 2 como en "
                        "HuggingFace: da 32, o sea 320x el default de la librería (0.1). "
                        "Con 32 el entrenamiento converge a emitir un token repetido y la "
                        "loss BAJA igual, porque esa salida tiene entropía casi nula. Es la "
                        "causa medida del colapso de lora_v1 y lora_v2. No subirlo sin "
                        "mirar el canario")
    p.add_argument("--dropout", type=float, default=0.05)
    p.add_argument("--resize", type=int, nargs=2, default=None, metavar=("ANCHO", "ALTO"),
                   help="redimensionar las imágenes, p.ej. --resize 560 980. Un comprobante "
                        "a tamaño completo son ~1222 tokens de imagen y es lo que domina el "
                        "tiempo por paso")
    p.add_argument("--salida", type=Path, default=AQUI / "checkpoints" / "lora_bancos")
    p.add_argument("--curva", type=Path, default=None,
                   help="CSV de la curva de loss. Default: <salida>/curva_loss.csv")
    p.add_argument("--cada", type=int, default=1, metavar="N",
                   help="guardar el adapter cada N pasos. 1 (default) = cada paso, y es "
                        "lo que corresponde: está medido que no alarga el entrenamiento")
    p.add_argument("--continuar", action="store_true",
                   help="reanudar desde el adapter y el estado.json que haya en --salida")
    p.add_argument("--canario", type=int, default=25, metavar="N",
                   help="cada N pasos, generar sobre --canario-imagen y verificar que la "
                        "salida siga siendo JSON. 0 lo apaga. LA LOSS NO DETECTA EL "
                        "COLAPSO: baja mientras el modelo aprende a repetir un token. Dos "
                        "corridas de 7 y 9 horas se perdieron enteras por no tener esto")
    p.add_argument("--canario-imagen", type=Path,
                   default=AQUI / "comprobantes" / "002.jpeg",
                   help="comprobante para el canario. Tiene que estar FUERA del dataset "
                        "de entrenamiento, o mide memorización en vez de salud")
    p.add_argument("--canario-tolerancia", type=int, default=3, metavar="K",
                   help="abortar tras K canarios fallidos seguidos. Uno suelto puede ser "
                        "ruido; tres seguidos es el colapso y seguir es quemar horas")
    args = p.parse_args()

    if args.cada < 1:
        raise SystemExit("--cada tiene que ser 1 o más")
    # Se valida ANTES de cargar el modelo, y es lo que habilita que el canario falle
    # cerrado: si la imagen está, cualquier error posterior es del modelo.
    if args.canario and not args.canario_imagen.exists():
        raise SystemExit(f"no existe la imagen del canario: {args.canario_imagen}")

    # Los nombres de archivo no son opcionales: "adapters.safetensors" es el que busca
    # apply_lora_layers para cargar el adapter, y save_adapter deja el adapter_config.json
    # al lado. Se resuelven acá arriba para poder rechazar un --continuar imposible ANTES
    # de los dos minutos que tarda en cargar el modelo.
    args.salida.mkdir(parents=True, exist_ok=True)
    pesos = args.salida / "adapters.safetensors"
    pesos_tmp = args.salida / "adapters.tmp.safetensors"
    optim_f = args.salida / "optimizador.safetensors"
    optim_tmp = args.salida / "optimizador.tmp.safetensors"
    estado = args.salida / "estado.json"
    estado_tmp = args.salida / "estado.tmp.json"
    # El mejor checkpoint vive en su propio directorio para que se pueda usar directo:
    # `extraer.py --adaptador <salida>/mejor`. Existe porque una corrida que diverge
    # pisa los pesos buenos paso a paso — pasó el 8-ago y costó 5 h de cómputo.
    mejor_dir = args.salida / "mejor"
    if args.continuar:
        faltan = [f.name for f in (pesos, optim_f, estado) if not f.exists()]
        if faltan:
            raise SystemExit(
                f"--continuar necesita {', '.join(faltan)} en {args.salida} y no está(n).\n"
                f"Si falta solo optimizador.safetensors, el checkpoint es de una versión "
                f"anterior de este script: reanudar sin el estado de Adam DIVERGE (medido, "
                f"la loss se fue de 7,9 a 31 en 25 pasos). Hay que arrancar de 0.")

    # Los imports pesados, después de parsear: `--help` no tiene por qué cargar mlx.
    import mlx.core as mx
    import mlx.optimizers as optim
    from mlx.utils import tree_flatten, tree_unflatten
    from datasets import load_dataset
    from transformers import Qwen2VLImageProcessor
    from mlx_vlm import load
    from mlx_vlm.utils import load_image_processor
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm import generate
    from mlx_vlm.trainer import Dataset, Trainer, save_adapter
    from mlx_vlm.trainer.utils import find_all_linear_names, get_peft_model

    # El canario mide con el MISMO prompt y el MISMO parseo que la extracción real:
    # si usara los suyos podría dar verde mientras `extraer.py` recibe basura.
    sys.path.insert(0, str(AQUI))
    from extraer import PROMPTS, parchear_detokenizador, parsear

    # El mismo parche que usa la extracción: sin esto, una tilde partida hace que el
    # canario reporte colapso cuando el problema es del detokenizador de la librería.
    parchear_detokenizador()

    curva = args.curva or args.salida / "curva_loss.csv"

    print(f"cargando {MODELO}...", flush=True)
    model, processor = load(MODELO, processor_config={"trust_remote_code": True})

    # (1) el parche. Sin esta línea el primer train_step explota.
    processor.image_processor = Qwen2VLImageProcessor.from_pretrained(
        MODELO, use_fast=False
    )

    config = model.config.__dict__
    image_processor = load_image_processor(MODELO)

    # `load_dataset(ruta)` a secas espera un directorio o un repo del Hub, y con
    # un directorio se lleva TODOS los .jsonl que encuentre — incluido el de los
    # comprobantes apartados para medir. Entrenar con la vara de medir invalida
    # el número de F10 sin dar ningún error. Se exige un archivo y se declara el
    # formato.
    if args.dataset.is_dir():
        raise SystemExit(
            f"--dataset tiene que ser un archivo .jsonl, no el directorio {args.dataset}. "
            f"Un directorio se lleva también los apartados de test.")
    if not args.dataset.exists():
        raise SystemExit(f"no existe {args.dataset}")
    if "test" in args.dataset.name:
        raise SystemExit(f"{args.dataset.name} parece el set de medición, no el de "
                         f"entrenamiento. Si es a propósito, renombralo.")

    ds = load_dataset("json", data_files=str(args.dataset), split="train")
    for columna in ("images", "messages"):
        if columna not in ds.column_names:
            raise SystemExit(f"al dataset le falta la columna {columna!r}: {ds.column_names}")

    def aplicar_template(ejemplos):
        ejemplos["messages"] = apply_chat_template(
            config=config, processor=processor,
            prompt=ejemplos["messages"], return_messages=True,
        )
        return ejemplos

    ds = ds.map(aplicar_template)
    datos = Dataset(ds, config, processor, image_processor=image_processor,
                    image_resize_shape=args.resize)

    model = get_peft_model(
        model,
        find_all_linear_names(model.language_model),
        rank=args.rank, alpha=args.alpha, dropout=args.dropout,
    )
    # save_adapter espera una ruta de ARCHIVO, no un directorio: internamente hace
    # mx.save_safetensors(str(ruta)), que le pega la extensión, y escribe el
    # adapter_config.json en ruta.parent. Pasándole el directorio quedaba un
    # "lora_bancos.safetensors" al lado de la carpeta. Así da la ruta que PLAN.md
    # pide como criterio de listo de F9.
    adapter = args.salida / "adapters"

    epoch_inicial, paso_inicial = 0, 0
    if args.continuar:
        previo = json.loads(estado.read_text(encoding="utf-8"))
        # strict=False es obligatorio — el checkpoint tiene solo los parámetros
        # entrenables, no el modelo entero — y por eso mismo NO avisa si los nombres
        # no coinciden: cargaría cero tensores y el entrenamiento seguiría desde pesos
        # random, sin un solo error, tirando otras 12 h a la basura. Se comparan las
        # claves a mano antes de cargar.
        guardados = mx.load(str(pesos))
        esperados = {k for k, _ in tree_flatten(model.trainable_parameters())}
        if set(guardados) != esperados:
            raise SystemExit(
                f"el checkpoint de {pesos} no corresponde a este modelo: {len(guardados)} "
                f"tensores guardados contra {len(esperados)} esperados. ¿Cambió --rank, "
                f"--alpha o el modelo base respecto de la corrida original?")
        model.load_weights(list(guardados.items()), strict=False)
        epoch_inicial, paso_inicial = previo["epoch"], previo["paso"] + 1

    # `train_on_completions=True` es la 5ta corrección a mlx-vlm y probablemente la más cara
    # de haber omitido. El DEFAULT de la librería es False, y con False `loss_fn` deja
    # `weight_mask = None`: la cross-entropy se calcula sobre TODA la secuencia — el prompt,
    # los tokens de imagen y la respuesta. O sea que el gradiente se gasta enseñándole al
    # modelo a predecir su propio prompt, que es idéntico en los 333 ejemplos y no es la
    # tarea. Es la explicación de la loss clavada en ~5,0 POR TOKEN (perplejidad ~150) y de
    # que 333 pasos de lora_v3 movieran casi lo mismo que los 40 de la calibración.
    #
    # Verificado antes de activarlo, porque la librería falla feo si no se cumple: enmascara
    # con `np.where(input_ids == assistant_id)[1]` y un `reshape(-1, 1)`, que asume UNA
    # aparición del token por secuencia. Medido sobre los 333 ejemplos de train_v3.jsonl:
    # exactamente 1 en cada uno. El "assistant." del system prompt de Qwen2 NO cuenta —
    # lleva espacio delante y tokeniza distinto de 77091.
    entrenador = Trainer(model, optim.Adam(learning_rate=args.lr),
                         train_on_completions=True)
    if args.continuar:
        # SIN esto la reanudación diverge. No es teoría: el 8-ago se reanudó con Adam en
        # cero y la loss se fue de 7,9 a 31 en 25 pasos, destruyendo 5 h de entrenamiento.
        # Con el estado restaurado, reanudar reproduce la corrida continua exactamente
        # (verificado: diferencia 0,0 contra no haber interrumpido nunca).
        entrenador.optimizer.state = tree_unflatten(list(mx.load(str(optim_f)).items()))
        paso_opt = int(mx.load(str(optim_f), return_metadata=True)[1].get("paso", -1))
        if paso_opt != previo["paso"]:
            raise SystemExit(
                f"checkpoint inconsistente: los pesos/estado dicen paso {previo['paso']} y "
                f"el optimizador dice {paso_opt}. Lo mataron en mitad del guardado. "
                f"Arrancá de 0, o desde {mejor_dir} si existe.")
    model.train()

    pasos = args.iteraciones or len(datos) // args.batch
    print(f"{len(datos)} ejemplos · {args.epochs} epoch(s) · {pasos} pasos · "
          f"batch {args.batch} · lr {args.lr} · rank {args.rank}", flush=True)
    if args.continuar:
        print(f"continuando desde epoch {epoch_inicial}, paso {paso_inicial + 1} "
              f"(último loss {previo['loss']:.4f}, guardado {previo['guardado']}), "
              f"con el estado de Adam restaurado.", flush=True)

    def guardar(epoch: int, paso: int, loss: float) -> None:
        """Pesos + estado de Adam + metadatos, de forma atómica.

        Se escribe a un temporal y recién ahí se renombra: `os.replace` es atómico
        dentro del mismo filesystem, así que un kill en mitad de la escritura deja
        intacto el checkpoint del paso anterior en vez de un archivo a medias.

        Los pesos van ANTES que el estado, a propósito: si lo matan entre las dos
        escrituras, el estado apunta a un paso más viejo y al reanudar se repite un
        paso, que es el error barato. Al revés se saltearía un paso en silencio.

        Los tres archivos no se pueden escribir en una sola operación atómica, así que
        cada safetensors lleva su número de paso en los metadatos y al reanudar se
        comparan: un checkpoint partido por la mitad se detecta en vez de entrenar
        sobre pesos y momentos de pasos distintos.
        """
        mx.save_safetensors(str(pesos_tmp),
                            dict(tree_flatten(model.trainable_parameters())),
                            metadata={"paso": str(paso)})
        os.replace(pesos_tmp, pesos)
        mx.save_safetensors(str(optim_tmp),
                            dict(tree_flatten(entrenador.optimizer.state)),
                            metadata={"paso": str(paso)})
        os.replace(optim_tmp, optim_f)
        estado_tmp.write_text(json.dumps({
            "epoch": epoch, "paso": paso, "loss": loss,
            "pasos": pasos, "epochs": args.epochs,
            "dataset": str(args.dataset), "modelo": MODELO,
            "lr": args.lr, "rank": args.rank, "alpha": args.alpha,
            "dropout": args.dropout, "batch": args.batch, "resize": args.resize,
            "guardado": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(estado_tmp, estado)

    # El adapter_config.json una sola vez: no cambia entre pasos y lo necesita
    # apply_lora_layers para poder cargar el adapter. De paso deja en disco un
    # adapter válido (sin entrenar) antes del primer paso.
    if not args.continuar:
        save_adapter(model, adapter)

    prompt_canario = (apply_chat_template(processor, model.config, PROMPTS["v3"], num_images=1)
                      if args.canario else None)

    def canario() -> tuple[bool, str]:
        """¿El modelo TODAVÍA produce JSON, o ya colapsó?

        La loss no puede responder esto. Un modelo que aprende a emitir el mismo token
        para siempre tiene entropía casi nula y por lo tanto loss BAJA: las curvas de
        lora_v1 y lora_v2 bajaban y convergían prolijamente hacia un modelo inservible.
        Generar de verdad cada tantos pasos es lo único que lo delata.

        FALLA CERRADO: cualquier excepción cuenta como colapso, no como "no sé". La
        imagen ya se validó al arrancar, así que lo único que queda variando es el
        modelo — y un modelo tan roto que su salida ni siquiera decodifica en UTF-8
        (visto, con alpha alto) reventaba acá y una versión anterior de esta función lo
        anotaba como "el chequeo falló", dejando pasar el colapso más grave de todos.
        """
        model.eval()                      # sin esto el dropout ensucia la generación
        try:
            salida = generate(model, processor, prompt_canario,
                              [str(args.canario_imagen)],
                              max_tokens=400, temperature=0.0, verbose=False)
            campos, crudo = parsear(salida)
            return campos is not None, (crudo or "").strip()[:50]
        except Exception as e:            # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"[:60]
        finally:
            model.train()

    def guardar_mejor(paso: int, media: float) -> None:
        """Copia del checkpoint recién escrito, en su propio directorio usable.

        `shutil.copyfile` sobre el archivo que `guardar()` acaba de dejar en disco, en
        vez de volver a serializar el modelo: evita forzar de nuevo el grafo de MLX y
        cuesta solo el disco. El directorio queda listo para usarse directo con
        `extraer.py --adaptador <salida>/mejor`.
        """
        mejor_dir.mkdir(exist_ok=True)
        shutil.copyfile(args.salida / "adapter_config.json", mejor_dir / "adapter_config.json")
        shutil.copyfile(pesos, mejor_dir / "adapters.safetensors")
        (mejor_dir / "estado.json").write_text(json.dumps(
            {"paso": paso, "media_20": media, "guardado": time.strftime("%Y-%m-%d %H:%M:%S")},
            indent=2), encoding="utf-8")

    # Al continuar se agrega a la curva vieja en vez de pisarla: es material del
    # informe y la parte ya corrida no se vuelve a calcular.
    modo = "a" if args.continuar else "w"
    ultimo: tuple[int, int, float] | None = None
    hechos = 0
    # El "mejor" se juzga por la media de las últimas 20 losses, no por la de un paso:
    # con batch 1 la loss por paso salta de 8 a 48 según el ejemplo que toque, y un
    # mínimo puntual sería ruido, no un modelo mejor.
    ventana: list[float] = []
    fallos = 0                      # canarios fallidos seguidos
    # Al reanudar se recupera la marca anterior: si arrancara en infinito, los primeros
    # 20 pasos pisarían el mejor checkpoint con uno peor, que es justo lo que esto evita.
    mejor_media = float("inf")
    if args.continuar and (mejor_dir / "estado.json").exists():
        mejor_media = json.loads((mejor_dir / "estado.json").read_text())["media_20"]
        print(f"mejor checkpoint previo: media_20 {mejor_media:.3f}", flush=True)
    with curva.open(modo, newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if modo == "w":
            w.writerow(["epoch", "paso", "loss", "segundos"])
        arranque = time.monotonic()
        try:
            for epoch in range(epoch_inicial, args.epochs):
                desde = paso_inicial if epoch == epoch_inicial else 0
                for i in range(desde, pasos):
                    t0 = time.monotonic()
                    # Con batch 1 se indexa con ENTERO, no con slice. `lora.py` usa
                    # slice siempre, y ahí `prepare_inputs` recibe images anidado
                    # ([[ruta]] en vez de [ruta]); con --resize eso revienta en
                    # resize_image con "'list' object has no attribute 'width'".
                    # Es un bug de mlx-vlm 0.1.15, no del dataset.
                    lote = (datos[i] if args.batch == 1
                            else datos[i * args.batch:(i + 1) * args.batch])
                    loss = entrenador.train_step(lote)
                    # mlx es perezoso: sin forzar la evaluación acá, el cronómetro
                    # mide armar el grafo (décimas de segundo) y no el cómputo real.
                    valor = loss.item()
                    dt = time.monotonic() - t0
                    w.writerow([epoch, i, f"{valor:.6f}", f"{dt:.2f}"])
                    f.flush()  # que la curva sobreviva a un Ctrl-C
                    ultimo = (epoch, i, valor)
                    hechos += 1
                    marca = ""
                    if hechos % args.cada == 0:
                        guardar(*ultimo)
                        marca = " · ✓"
                        ventana.append(valor)
                        if len(ventana) >= 20:
                            media = sum(ventana[-20:]) / 20
                            if media < mejor_media:
                                # La red de seguridad no puede tumbar el entrenamiento:
                                # es una copia de conveniencia y perderla cuesta mucho
                                # menos que perder la corrida entera por su culpa.
                                try:
                                    guardar_mejor(i, media)
                                    mejor_media = media
                                    marca += f" · MEJOR ({media:.3f})"
                                except OSError as e:
                                    marca += f" · [no pude copiar el mejor: {e}]"
                    if args.canario and hechos % args.canario == 0:
                        sano, muestra = canario()
                        if sano:
                            fallos = 0
                            marca += " · 🐤"
                        else:
                            fallos += 1
                            marca += f" · 🐤✗ {fallos}/{args.canario_tolerancia} {muestra!r}"
                    print(f"  epoch {epoch} · paso {i+1}/{pasos} · "
                          f"loss {valor:.4f} · {dt:.1f}s{marca}", flush=True)
                    if fallos >= args.canario_tolerancia:
                        guardar(*ultimo)
                        raise SystemExit(
                            f"\nABORTADO en el paso {i+1}: {fallos} canarios fallidos "
                            f"seguidos. El modelo dejó de producir JSON — está colapsando, "
                            f"y la loss no lo muestra. Última salida cruda: {muestra!r}\n"
                            f"Bajar --alpha (mlx-vlm usa la escala directa: su default es "
                            f"0.1) o --lr, y volver a probar con una corrida corta.\n"
                            f"El mejor checkpoint sano, si llegó a haber uno, está en "
                            f"{mejor_dir}.")
        except KeyboardInterrupt:
            if ultimo is not None:
                guardar(*ultimo)
                print(f"\ninterrumpido en el paso {ultimo[1] + 1}/{pasos} · checkpoint "
                      f"guardado\nreanudar con: --continuar --salida {args.salida}",
                      flush=True)
            raise SystemExit(130)

    if ultimo is not None:
        guardar(*ultimo)
    total = time.monotonic() - arranque
    print(f"\nadapters → {pesos}")
    print(f"estado   → {estado}")
    print(f"curva    → {curva}")
    if hechos:
        print(f"total {total/60:.1f} min · {total/hechos:.1f} s/paso · {hechos} pasos")


if __name__ == "__main__":
    main()
