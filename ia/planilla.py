"""Arma la planilla de corrección humana (F6) a partir de una extracción.

    ia/.venv/bin/python ia/planilla.py ia/salida_v2.jsonl ia/verdad_referencia.xlsx

Modo híbrido, a propósito:
  · los 4 campos CRÍTICOS van VACÍOS  → se tipean mirando el comprobante, sin
    ver lo que contestó el modelo. Evita el sesgo de anclaje justo donde duele:
    un CUIT de 11 dígitos "se ve bien" y puede estar equivocado.
  · los otros 12 van PRECARGADOS      → se corrige solo lo que está mal.

Todas las celdas se escriben como TEXTO. Si no, Excel convierte un CBU de 22
dígitos a notación científica y se pierde el dato en silencio.
"""

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Se tipean a ciegas: son cortos y son de los que depende el veredicto. Ver el
# comentario de arriba sobre el anclaje.
CRITICOS = ["monto", "fecha", "cuit_emisor", "coelsa_id"]

# Sin estos tres el comprobante no se puede cruzar contra el extracto (son los
# que mira el motor). Van primero para que completarlos desbloquee el trabajo.
OBLIGATORIOS = ["monto", "fecha", "cbu_cvu_receptor"]
SUMAN = ["cuit_emisor", "coelsa_id"]

BASURA = {"n/a", "na", "-", "--", "", "none", "null", "no disponible", "sin datos"}


def ordenar(campos):
    """Obligatorios primero, después los que suben la confianza, después el resto."""
    resto = [c for c in campos if c not in OBLIGATORIOS + SUMAN]
    return [c for c in OBLIGATORIOS if c in campos] + \
           [c for c in SUMAN if c in campos] + resto

ANCHOS = {"archivo": 11, "ilegible": 9, "nombre_emisor": 22, "nombre_receptor": 22,
          "cbu_cvu_emisor": 24, "cbu_cvu_receptor": 24, "coelsa_id": 24,
          "concepto": 20, "referencia": 16}

AZUL = PatternFill("solid", fgColor="DCE6F1")    # precargado: revisar
AMBAR = PatternFill("solid", fgColor="FCE4D6")   # vacío: tipear a mano
GRIS = PatternFill("solid", fgColor="D9D9D9")

INSTRUCCIONES = [
    ("Cómo completar esta planilla", True),
    ("", False),
    ("Son 30 comprobantes los que hacen falta. Están las 52 filas por si alguno sale ilegible.", False),
    ("", False),
    ("LAS 3 PRIMERAS COLUMNAS SON LAS QUE MANDAN.", True),
    ("   monto, fecha y cbu_cvu_receptor son los únicos campos sin los cuales el", False),
    ("   comprobante NO se puede cruzar contra el extracto del banco.", False),
    ("   Si solo tenés tiempo para una cosa, completá esas tres.", False),
    ("", False),
    ("   Las dos siguientes (cuit_emisor, coelsa_id) NO son necesarias: solo suben", False),
    ("   la confianza del cruce. Que falten no impide conciliar.", False),
    ("   Las demás son informativas y no cambian ningún veredicto.", False),
    ("", False),
    ("COLUMNAS ÁMBAR (monto, fecha, cuit_emisor, coelsa_id) — están VACÍAS a propósito.", True),
    ("   Completalas mirando el comprobante, sin fijarte en lo que dijo la IA.", False),
    ("   Son los 4 campos de los que depende toda la conciliación. Si te mostrara la", False),
    ("   respuesta de la IA, el ojo tiende a darla por buena — y un CUIT mal leído", False),
    ("   con 11 dígitos parece perfectamente válido.", False),
    ("", False),
    ("COLUMNAS AZULES — vienen con lo que extrajo la IA.", True),
    ("   Solo corregí lo que esté mal. Si está bien, no toques nada.", False),
    ("", False),
    ("FORMATOS (importan, la conciliación los cruza literal):", True),
    ("   monto        solo el número con punto decimal:  15000.50", False),
    ("   fecha        YYYY-MM-DD:  2026-06-16", False),
    ("   cuit         11 dígitos sin guiones:  20123456789", False),
    ("   cbu / cvu    22 dígitos", False),
    ("   coelsa_id    22 caracteres alfanuméricos en MAYÚSCULA", False),
    ("", False),
    ("SI EL DATO NO ESTÁ EN EL COMPROBANTE: dejá la celda vacía.", True),
    ("   Vacío significa 'no figura'. No pongas N/A, ni un guión, ni lo deduzcas.", False),
    ("   Un dato inventado acá se convierte después en una acusación falsa.", False),
    ("", False),
    ("SI EL COMPROBANTE NO SE LEE: escribí una x en la columna 'ilegible'", True),
    ("   y pasá al siguiente. No adivines.", False),
    ("", False),
    ("Hacé click en el nombre del archivo (columna A) para abrir el comprobante.", False),
]


def limpiar(v):
    """El valor listo para precargar, o vacío si el modelo escribió basura."""
    if v is None or str(v).strip().lower() in BASURA:
        return ""
    return str(v)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    origen, destino = Path(sys.argv[1]), Path(sys.argv[2])

    filas = [json.loads(l) for l in open(origen)]
    campos = ordenar(list(filas[0]["campos"] or {}) or CRITICOS)

    wb = Workbook()

    # --- hoja de instrucciones, primero: es lo que se ve al abrir
    ins = wb.active
    ins.title = "Instrucciones"
    ins.column_dimensions["A"].width = 95
    for i, (texto, negrita) in enumerate(INSTRUCCIONES, 1):
        c = ins.cell(i, 1, texto)
        c.font = Font(bold=negrita, size=13 if i == 1 else 11)

    # --- hoja de corrección
    hoja = wb.create_sheet("Corrección")
    encabezados = ["archivo", "ilegible"] + campos
    for col, nombre in enumerate(encabezados, 1):
        c = hoja.cell(1, col, nombre)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
        c.fill = AMBAR if nombre in CRITICOS else (GRIS if col <= 2 else AZUL)
        hoja.column_dimensions[get_column_letter(col)].width = ANCHOS.get(nombre, 15)

    for fila, registro in enumerate(filas, 2):
        archivo = registro["archivo"]
        c = hoja.cell(fila, 1, archivo)
        # click en el nombre → abre el comprobante. La ruta es relativa a la planilla.
        c.hyperlink = f"comprobantes/{archivo}"
        c.font = Font(color="0563C1", underline="single")

        hoja.cell(fila, 2, "")
        # si el jsonl pasó por validar.py se usa `confiables`: los campos que no
        # pasaron la validación llegan en null y se precargan vacíos. Precargar
        # un CBU mal formado sería anclar a la persona a un dato ya sospechoso.
        extraido = registro.get("confiables") or registro["campos"] or {}
        for col, campo in enumerate(campos, 3):
            valor = "" if campo in CRITICOS else limpiar(extraido.get(campo))
            celda = hoja.cell(fila, col, valor)
            celda.number_format = "@"          # TEXTO: sin esto Excel rompe los CBU
            celda.fill = AMBAR if campo in CRITICOS else AZUL

    hoja.freeze_panes = "C2"
    wb.save(destino)

    n_criticos = len(CRITICOS) * len(filas)
    print(f"{destino}")
    print(f"  {len(filas)} comprobantes · {len(campos)} campos")
    print(f"  {n_criticos} celdas a tipear (ámbar) · {len(filas) * (len(campos) - len(CRITICOS))} a revisar (azul)")


if __name__ == "__main__":
    main()
