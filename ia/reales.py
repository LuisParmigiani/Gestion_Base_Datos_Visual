"""
Los comprobantes REALES corregidos a mano, como dataset de entrenamiento.

    ia/.venv/bin/python ia/reales.py \
        --sinteticos ia/sinteticos/train.jsonl \
        --salida     ia/sinteticos/train_v2.jsonl \
        --test       ia/sinteticos/test_reales.jsonl

Lee de Postgres la verdad que una persona confirmó campo por campo en /revisar,
la vuelca en el mismo formato `images`/`messages` que `generar.py`, y la parte
en dos: unos para entrenar y otros que **no se entrenan nunca**.

Por qué la partición importa más que nada:
  Si el modelo se entrena con los mismos comprobantes con que después se lo mide,
  el número que sale no dice "aprendió a leer comprobantes", dice "se acordó de
  estos". Los apartados son la única prueba de que sirve en uno que nunca vio.

La partición está FIJA por nombre de archivo (ver `APARTADOS`) y se imprime
entera al correr. Antes se sorteaba con semilla fija, pero el sorteo era sobre el
conjunto de revisados: cada comprobante nuevo cambiaba cuáles eran los 16 y la
medición dejaba de ser comparable con la anterior. Todo lo que no está apartado
entrena, así que sumar comprobantes solo agranda el entrenamiento.

Las etiquetas salen canónicas —monto `15000.50`, fecha `2026-06-01`, hora
`21:46`— igual que en `generar.py`, porque es el formato que la conciliación
necesita y el que el modelo tiene que aprender a producir.
"""

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image

from extraer import CAMPOS, PROMPT_V3

AQUI = Path(__file__).resolve().parent
IMAGENES = AQUI / "comprobantes"
REDUCIDAS = AQUI / "comprobantes_reducidos"

# Qwen2-VL no achica a un tamaño fijo: consume un token cada 28x28 px, así que
# los tokens escalan con el ÁREA (medido con el procesador instalado). El tope
# probado del entrenamiento es 1.848; 3.078 y 3.534 mataron el proceso sin dejar
# traceback y costaron las corridas del 7 y del 8 de agosto de 2026.
#
# Antes esto se esquivaba a mano, sacando esos comprobantes del dataset: por eso
# existía `train_v2_sin_gigantes.jsonl`. Acordarse no es una estrategia — el
# 2026-08-11 `reales.py` los volvió a meter solo. Ahora se mide y se achica.
TOPE_TOKENS = 1800          # margen bajo el 1.848 probado
PX_POR_TOKEN = 28 * 28
# ponytail: se lee con el psql que ya está instalado en vez de agregar psycopg
# al venv. Son 51 filas una vez por corrida: no justifica una dependencia.
PSQL = "/Applications/Postgres.app/Contents/Versions/18/bin/psql"
BASE = "conciliador"

# Los 16 apartados, FIJOS por nombre. Salieron del sorteo con semilla 2026 sobre
# los 51 revisados que había el 2026-08-10, y son la vara de F10: todo número
# publicado del proyecto está medido sobre estos y nada más.
#
# Por qué dejaron de sortearse (decisión del 2026-08-11): el sorteo era sobre el
# CONJUNTO de revisados, así que cada comprobante nuevo que se revisaba cambiaba
# cuáles eran los 16 y ningún número anterior volvía a ser comparable. Con 58
# revisados ya habrían sido otros. Fijarlos cuesta una constante y hace que la
# vara sobreviva a todas las tandas de comprobantes que vengan.
#
# ⛔ Esta lista NO se toca. Agregar uno acá lo saca del entrenamiento; sacar uno
# lo mete, y en los dos casos la medición histórica deja de valer.
APARTADOS = frozenset({
    "002.jpeg", "003.jpeg", "005.jpeg", "010.jpeg", "014.jpeg", "018.jpeg",
    "019.jpeg", "021.jpeg", "024.jpeg", "025.jpeg", "026.jpeg", "029.jpeg",
    "031.jpeg", "035.jpeg", "044.jpeg", "049.jpeg",
})

# Las 16 columnas tipadas de `comprobante`, ya canonizadas por Postgres. Es la
# misma conversión que hace `normalizarCampo` en la web: los tres campos con
# tipo propio se formatean y los otros trece son TEXT y salen tal cual.
CONSULTA = """
SELECT coalesce(json_agg(t), '[]') FROM (
SELECT archivo, tipo_operacion,
       to_char(monto, 'FM999999999990.00') AS monto,
       moneda,
       to_char(fecha, 'YYYY-MM-DD') AS fecha,
       to_char(hora, 'HH24:MI')     AS hora,
       nombre_emisor, cuit_emisor, cbu_cvu_emisor, banco_emisor,
       nombre_receptor, cuit_receptor, cbu_cvu_receptor, banco_receptor,
       concepto, referencia, coelsa_id
FROM comprobante
WHERE revisado_en IS NOT NULL AND corrida_base <> 'sintetico'
ORDER BY archivo
) t
"""


def leer_verdad() -> list[dict]:
    """Los comprobantes revisados, vía el psql instalado. Nunca imprime valores."""
    r = subprocess.run([PSQL, "-d", BASE, "-t", "-A", "-c", CONSULTA],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"psql falló — ¿está levantado Postgres?\n{r.stderr.strip()}")
    return json.loads(r.stdout.strip())


def tokens_de(w: int, h: int) -> int:
    return (w // 28) * (h // 28)


def imagen_para_entrenar(ruta: Path) -> Path:
    """La misma imagen, o una copia achicada si no entra en el tope de tokens.

    El original NUNCA se toca: lo muestra `/revisar` y es el comprobante que la
    persona miró para escribir la verdad. La copia va aparte y solo la usa el
    entrenamiento.
    """
    with Image.open(ruta) as im:
        w, h = im.size
        if tokens_de(w, h) <= TOPE_TOKENS:
            return ruta

        destino = REDUCIDAS / ruta.name
        factor = ((TOPE_TOKENS * PX_POR_TOKEN) / (w * h)) ** 0.5
        nuevo = (int(w * factor), int(h * factor))
        if not destino.exists():
            REDUCIDAS.mkdir(exist_ok=True)
            im.convert("RGB").resize(nuevo, Image.LANCZOS).save(
                destino, "JPEG", quality=95, optimize=True)
        print(f"  achicado {ruta.name}: {w}x{h} ({tokens_de(w, h):,} tokens) → "
              f"{nuevo[0]}x{nuevo[1]} ({tokens_de(*nuevo):,})")
        return destino


def registro(fila: dict, para_entrenar: bool = True) -> dict:
    """Un ejemplo en el formato que lee `mlx_vlm.trainer.Dataset` de 0.1.15.

    `content` va como STRING PLANO en los dos mensajes. Está explicado largo en
    `generar.py`: `lora.py` reconstruye los mensajes con su propio wrapper, y si
    se le pasa una lista de dicts la etiqueta que el modelo aprende termina
    siendo la repr de Python de una lista. No da error: entrena y sale basura.
    """
    ruta = IMAGENES / fila["archivo"]
    if not ruta.exists():
        sys.exit(f"falta la imagen {ruta} — ¿se borró el comprobante de la base?")

    # El tope de tokens es un problema del ENTRENAMIENTO, no de la inferencia:
    # los 51 se extrajeron enteros sin drama. Achicar un apartado cambiaría la
    # vara en silencio, así que la vara se entrega siempre en tamaño original.
    if para_entrenar:
        ruta = imagen_para_entrenar(ruta)

    etiqueta = {c: (fila[c] if fila[c] not in ("", None) else None) for c in CAMPOS}
    return {
        "images": [str(ruta)],
        "messages": [
            {"role": "user", "content": PROMPT_V3},
            {"role": "assistant", "content": json.dumps(etiqueta, ensure_ascii=False)},
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--semilla", type=int, default=2026,
                   help="mezcla el orden del dataset de entrenamiento")
    p.add_argument("--sinteticos", type=Path, default=None,
                   help="jsonl sintético con el que mezclar los reales de entrenamiento")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--test", type=Path, required=True)
    args = p.parse_args()

    filas = leer_verdad()

    # La vara tiene que estar ENTERA o el número no se compara con ninguno de los
    # publicados. Si falta uno se corta acá: entrenar con 15 apartados en vez de
    # 16 daría un porcentaje que parece el de siempre y mide otra cosa.
    presentes = {f["archivo"] for f in filas}
    faltan = APARTADOS - presentes
    if faltan:
        sys.exit(f"faltan {len(faltan)} de los 16 apartados entre los revisados: "
                 f"{' '.join(sorted(faltan))}. Son la vara de F10 y no se puede "
                 f"medir sin ellos — revisalos en /revisar antes de entrenar.")

    # Partición FIJA por nombre: los 16 de siempre se apartan y TODO el resto
    # entrena, incluidos los que se vayan revisando de acá en adelante.
    test = sorted((f for f in filas if f["archivo"] in APARTADOS), key=lambda f: f["archivo"])
    train = sorted((f for f in filas if f["archivo"] not in APARTADOS), key=lambda f: f["archivo"])

    sinteticos = []
    if args.sinteticos:
        sinteticos = [json.loads(l) for l in
                      args.sinteticos.read_text(encoding="utf-8").splitlines() if l.strip()]

    mezcla = sinteticos + [registro(f) for f in train]
    random.Random(args.semilla).shuffle(mezcla)

    args.salida.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mezcla), encoding="utf-8")
    args.test.write_text(
        "".join(json.dumps(registro(f, para_entrenar=False), ensure_ascii=False) + "\n"
                for f in test),
        encoding="utf-8")

    print(f"entrenamiento → {args.salida}")
    print(f"  {len(sinteticos)} sintéticos + {len(train)} reales = {len(mezcla)} ejemplos")
    print(f"apartados     → {args.test}   ({len(test)} reales que NO se entrenan)")
    print(f"\nLos {len(test)} apartados (FIJOS, la vara de F10 — no cambian "
          f"aunque se agreguen comprobantes):")
    print("  " + " ".join(sorted(f["archivo"] for f in test)))


if __name__ == "__main__":
    main()
