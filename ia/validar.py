"""Marca qué campos la IA no extrajo con confianza, para cargarlos a mano.

    ia/.venv/bin/python ia/validar.py ia/salida_v2.jsonl ia/validado.jsonl

No corrige ni adivina: solo separa lo confiable de lo que no lo es. Un CUIT con
10 dígitos no se guarda como si fuera un CUIT — se marca y se pide a una persona.

Distingue dos situaciones que NO son lo mismo:

  faltan   el campo es crítico y vino vacío. Sin monto o sin fecha no hay
           conciliación posible: hay que completarlo sí o sí.

  revisar  el modelo escribió algo pero está mal formado. Es el caso peligroso:
           un valor mal leído que parece válido puede cruzar contra el
           movimiento equivocado y acusar a alguien que pagó.

Un campo ausente y bien ausente no aparece en ninguna lista. Que un comprobante
no traiga COELSA es normal: en el extracto real solo lo trae el 3% de las filas.
"""

import json
import re
import sys

def normalizar_monto(v):
    """El monto como float, o None si es ambiguo o no es un número.

    Misma regla que F2 aplica al extracto, por el mismo motivo: hay dos formatos
    mezclados ($ 368.500,00 y $ 16,000.00) y un importe mal leído no rompe nada
    visible, solo produce una acusación falsa.

        dos separadores  → el último es el decimal      368.500,00 → 368500.00
        uno, 1-2 dígitos → decimal                      1.50       →      1.50
        uno, 3 dígitos   → AMBIGUO, no se adivina       1.500      →      None
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None

    s = re.sub(r"[^\d.,]", "", str(v))
    if not s or not re.search(r"\d", s):
        return None

    if "." in s and "," in s:
        decimal = max(s.rfind("."), s.rfind(","))
        entero = re.sub(r"\D", "", s[:decimal])
        resto = re.sub(r"\D", "", s[decimal + 1:])
    elif "." in s or "," in s:
        sep = s.rfind(".") if "." in s else s.rfind(",")
        if s.count(".") + s.count(",") > 1:      # 1.234.567 → separador de miles
            return float(re.sub(r"\D", "", s)) or None
        resto = s[sep + 1:]
        if len(resto) == 3:                       # 1.500 = mil quinientos o 1,50?
            return None                           # no se adivina
        entero = s[:sep]
    else:
        return float(s) if float(s) > 0 else None

    valor = float(f"{entero or 0}.{resto or 0}")
    return valor if valor > 0 else None


# Los formatos que el proyecto ya midió contra el extracto real: los COELSA
# miden 22, los CBU 22, los CUIT 11.
REGLAS = {
    "monto":            lambda v: normalizar_monto(v) is not None,
    "fecha":            lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))),
    "hora":             lambda v: bool(re.fullmatch(r"\d{2}:\d{2}", str(v))),
    "moneda":           lambda v: str(v).strip().upper() in {"ARS", "USD"},
    "cuit_emisor":      lambda v: bool(re.fullmatch(r"\d{11}", re.sub(r"\D", "", str(v)))),
    "cuit_receptor":    lambda v: bool(re.fullmatch(r"\d{11}", re.sub(r"\D", "", str(v)))),
    "cbu_cvu_emisor":   lambda v: bool(re.fullmatch(r"\d{22}", re.sub(r"\D", "", str(v)))),
    "cbu_cvu_receptor": lambda v: bool(re.fullmatch(r"\d{22}", re.sub(r"\D", "", str(v)))),
    "coelsa_id":        lambda v: bool(re.fullmatch(r"[A-Z0-9]{22}", str(v).strip())),
}

# Los únicos campos que el motor mira. Verificado contra el type Comprobante de
# web/src/lib/motor.ts: los otros 11 campos no cambian ni un veredicto.
#
#   obligatorios  sin ellos el comprobante no se puede cruzar contra el extracto.
#                 cbu_cvu_receptor es el que dice a qué cuenta apunta: sin él el
#                 motor devuelve no_verificable aunque el movimiento esté.
#   opcionales    suben la confianza del match, no lo habilitan:
#                 coelsa_id → regla 1 · cuit_emisor → regla 2
#                 sin ninguno de los dos igual se concilia por regla 3.
OBLIGATORIOS = ["monto", "fecha", "cbu_cvu_receptor"]
SUMAN_CONFIANZA = ["coelsa_id", "cuit_emisor"]

# Lo que el modelo escribe cuando quiere decir "no está", pese a pedirle null.
BASURA = {"n/a", "na", "-", "--", "", "none", "null", "no disponible", "sin datos",
          "no especificado", "no figura", "desconocido"}


def vacio(v):
    return v is None or str(v).strip().lower() in BASURA


def validar(campos):
    """(confiables, revisar, faltan) — nunca corrige, solo clasifica."""
    confiables, revisar, faltan = {}, [], []
    for campo, valor in campos.items():
        if vacio(valor):
            confiables[campo] = None
            if campo in OBLIGATORIOS:
                faltan.append(campo)
            continue
        regla = REGLAS.get(campo)
        if regla is None or regla(valor):
            confiables[campo] = valor
        else:
            # se leyó algo, pero no tiene la forma que debería: no se confía
            confiables[campo] = None
            revisar.append(campo)
    return confiables, revisar, faltan


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)

    salida = open(sys.argv[2], "w")
    total = conciliables = 0
    por_campo, bloqueos = {}, {}

    for linea in open(sys.argv[1]):
        r = json.loads(linea)
        total += 1
        if r["sin_parsear"] is not None:
            # el modelo no devolvió JSON: el comprobante entero va a mano
            registro = {**r, "confiables": None, "revisar": [], "faltan": OBLIGATORIOS,
                        "conciliable": False}
            for c in OBLIGATORIOS:
                bloqueos[c] = bloqueos.get(c, 0) + 1
        else:
            confiables, revisar, faltan = validar(r["campos"])
            frena = [c for c in OBLIGATORIOS if confiables.get(c) is None]
            registro = {**r, "confiables": confiables, "revisar": revisar,
                        "faltan": faltan, "conciliable": not frena}
            if not frena:
                conciliables += 1
            for c in frena:
                bloqueos[c] = bloqueos.get(c, 0) + 1
            for c in revisar + faltan:
                por_campo[c] = por_campo.get(c, 0) + 1
        salida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    salida.close()

    print(f"{sys.argv[2]}\n")
    print(f"{conciliables}/{total} se pueden cruzar contra el extracto tal como están")
    print(f"{total - conciliables}/{total} no: les falta alguno de los 3 campos obligatorios\n")

    if bloqueos:
        print("qué falta para poder conciliar (lo único que frena):")
        for campo, n in sorted(bloqueos.items(), key=lambda x: -x[1]):
            print(f"    {campo:<20} falta en {n:>3}/{total}")
    if por_campo:
        print("\ncampos que solo suben la confianza (no frenan nada):")
        for campo, n in sorted(por_campo.items(), key=lambda x: -x[1]):
            if campo not in OBLIGATORIOS:
                print(f"    {campo:<20} {n:>3}/{total}")
    print("\nNingún valor se corrigió ni se dedujo: lo que no pasó la validación quedó en null.")


if __name__ == "__main__":
    main()
