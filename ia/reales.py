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

La partición es DETERMINÍSTICA (semilla fija) y se imprime entera al correr, así
que se puede repetir y auditar en cualquier momento.

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

from extraer import CAMPOS, PROMPT_V3

AQUI = Path(__file__).resolve().parent
IMAGENES = AQUI / "comprobantes"
# ponytail: se lee con el psql que ya está instalado en vez de agregar psycopg
# al venv. Son 51 filas una vez por corrida: no justifica una dependencia.
PSQL = "/Applications/Postgres.app/Contents/Versions/18/bin/psql"
BASE = "conciliador"

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


def registro(fila: dict) -> dict:
    """Un ejemplo en el formato que lee `mlx_vlm.trainer.Dataset` de 0.1.15.

    `content` va como STRING PLANO en los dos mensajes. Está explicado largo en
    `generar.py`: `lora.py` reconstruye los mensajes con su propio wrapper, y si
    se le pasa una lista de dicts la etiqueta que el modelo aprende termina
    siendo la repr de Python de una lista. No da error: entrena y sale basura.
    """
    ruta = IMAGENES / fila["archivo"]
    if not ruta.exists():
        sys.exit(f"falta la imagen {ruta} — ¿se borró el comprobante de la base?")

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
    p.add_argument("--n-test", type=int, default=16,
                   help="cuántos reales se apartan y NO se entrenan nunca")
    p.add_argument("--semilla", type=int, default=2026,
                   help="fija la partición: la misma semilla da los mismos apartados")
    p.add_argument("--sinteticos", type=Path, default=None,
                   help="jsonl sintético con el que mezclar los reales de entrenamiento")
    p.add_argument("--salida", type=Path, required=True)
    p.add_argument("--test", type=Path, required=True)
    args = p.parse_args()

    filas = leer_verdad()

    if len(filas) <= args.n_test:
        sys.exit(f"solo hay {len(filas)} reales revisados: no alcanza para apartar "
                 f"{args.n_test}. Revisá más en /revisar antes de entrenar.")

    # Se ordena por archivo antes de mezclar para que la partición no dependa
    # del orden en que Postgres devuelva las filas.
    orden = sorted(filas, key=lambda f: f["archivo"])
    random.Random(args.semilla).shuffle(orden)
    test, train = orden[:args.n_test], orden[args.n_test:]

    sinteticos = []
    if args.sinteticos:
        sinteticos = [json.loads(l) for l in
                      args.sinteticos.read_text(encoding="utf-8").splitlines() if l.strip()]

    mezcla = sinteticos + [registro(f) for f in train]
    random.Random(args.semilla).shuffle(mezcla)

    args.salida.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mezcla), encoding="utf-8")
    args.test.write_text(
        "".join(json.dumps(registro(f), ensure_ascii=False) + "\n" for f in test),
        encoding="utf-8")

    print(f"entrenamiento → {args.salida}")
    print(f"  {len(sinteticos)} sintéticos + {len(train)} reales = {len(mezcla)} ejemplos")
    print(f"apartados     → {args.test}   ({len(test)} reales que NO se entrenan)")
    print(f"\nLos {len(test)} apartados, con semilla {args.semilla} "
          f"(anotar: son la vara de F10):")
    print("  " + " ".join(sorted(f["archivo"] for f in test)))


if __name__ == "__main__":
    main()
