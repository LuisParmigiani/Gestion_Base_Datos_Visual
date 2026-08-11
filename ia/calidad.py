"""Mide la calidad de FORMATO de una extracción, sin mirar los valores.

    ia/.venv/bin/python ia/calidad.py ia/salida_v2.jsonl
    ia/.venv/bin/python ia/calidad.py ia/salida_cruda.jsonl ia/salida_v2.jsonl

Con dos archivos compara el segundo contra el primero.

IMPORTANTE: este script no imprime NUNCA el valor de un campo, solo cuentas y
formatos. Es lo que permite mirar el resultado sin que los datos bancarios
salgan de la máquina.

Formato ≠ exactitud. Un CUIT de 11 dígitos puede ser el CUIT equivocado; eso
solo lo dice la verdad de referencia corregida a mano (F6).
"""

import json
import sys
from pathlib import Path

CRITICOS = ["monto", "fecha", "cuit_emisor", "coelsa_id"]

# Las reglas viven en validar.py, que es quien decide qué se carga a mano.
# Medir con una regla distinta a la que decide daría un número que no
# corresponde con lo que después pasa de verdad.
sys.path.insert(0, str(Path(__file__).parent))
from validar import BASURA, REGLAS  # noqa: E402


def cargar(ruta):
    filas = [json.loads(l) for l in open(ruta)]
    return filas, [f["campos"] for f in filas if f["sin_parsear"] is None]


def medir(ok):
    """Por campo: cuántos traen dato, cuántos son basura, cuántos bien formados."""
    out = {}
    for campo in ok[0]:
        con_dato = [c[campo] for c in ok if c[campo] is not None]
        basura = [v for v in con_dato if str(v).strip().lower() in BASURA]
        regla = REGLAS.get(campo)
        validos = [v for v in con_dato if regla(v)] if regla else None
        out[campo] = {
            "presentes": len(con_dato),
            "basura": len(basura),
            "validos": len(validos) if validos is not None else None,
        }
    return out


def informe(nombre, filas, ok):
    malos = [f["archivo"] for f in filas if f["sin_parsear"] is not None]
    print(f"\n{'=' * 64}\n{nombre}")
    print(f"{'=' * 64}")
    print(f"comprobantes {len(filas)} · JSON válido {len(ok)} · no parsearon {len(malos)}")
    if malos:
        print("  sin parsear:", ", ".join(malos))
    return medir(ok)


def tabla(m, total, ref=None):
    print(f"\n{'campo':<19}{'con dato':>10}{'basura':>9}{'bien formado':>15}")
    print("-" * 64)
    for campo, d in m.items():
        val = "—" if d["validos"] is None else f"{d['validos']}/{d['presentes']}"
        delta = ""
        if ref and ref[campo]["validos"] is not None and d["validos"] is not None:
            dif = d["validos"] - ref[campo]["validos"]
            delta = f"  {dif:+d}" if dif else "   ="
        marca = " *" if campo in CRITICOS else "  "
        print(f"{marca}{campo:<17}{d['presentes']:>7}/{total}{d['basura']:>9}{val:>15}{delta}")
    print("\n  * = campo crítico para la conciliación")


def main():
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)

    filas_a, ok_a = cargar(sys.argv[1])
    m_a = informe(sys.argv[1], filas_a, ok_a)

    if len(sys.argv) == 2:
        tabla(m_a, len(ok_a))
        return

    filas_b, ok_b = cargar(sys.argv[2])
    tabla(m_a, len(ok_a))
    m_b = informe(sys.argv[2], filas_b, ok_b)
    tabla(m_b, len(ok_b), ref=m_a)


if __name__ == "__main__":
    main()
