"""El extracto completo a Excel, con qué comprobante le corresponde a cada fila.

Una fila por movimiento del banco, más tres columnas: **si se encontró
comprobante, con qué certeza, y el nombre del archivo**. Las filas se pintan
para que se lea de un vistazo:

    🟢 verde     cruzó al 90% o lo eligió el dueño     → se puede dar por bueno
    🟡 amarillo  cruzó solo al 50% (monto + fecha)     → mirarlo antes de confiar
    🔴 rojo      ningún comprobante lo reclama         → falta que alguien lo suba

Se exporta lo mismo que muestra la pantalla: no se recalcula nada acá, para que
el Excel no pueda decir algo distinto de la base.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from portal.modelos import Cliente, Comprobante, MovimientoBanco

COLUMNAS = [
    ("Cuenta", 18), ("Hoja", 14), ("Fila", 7), ("Fecha", 12),
    ("Nro transacción", 18), ("Descripción", 52), ("Importe", 14),
    ("¿Encontró comprobante?", 22), ("Certeza", 22), ("Archivo del comprobante", 38),
    ("Cliente", 24),
]

VERDE = PatternFill("solid", fgColor="D6EFDC")
AMARILLO = PatternFill("solid", fgColor="FFF2CC")
ROJO = PatternFill("solid", fgColor="FCE4E4")
ENCABEZADO = PatternFill("solid", fgColor="1F4F8B")


def _certeza(confianza: int | None) -> tuple[str, PatternFill]:
    if confianza is None:
        return "—", ROJO
    if confianza >= 100:
        return "Elegido por el dueño", VERDE
    if confianza >= 90:
        return "90% · nro de transacción o CUIT", VERDE
    return "50% · solo monto y fecha", AMARILLO


def a_excel(sesion) -> bytes:
    """Devuelve el .xlsx entero como bytes."""
    filas = sesion.execute(
        select(MovimientoBanco, Comprobante, Cliente)
        .outerjoin(Comprobante, Comprobante.id == MovimientoBanco.comprobante_id)
        .outerjoin(Cliente, Cliente.id == Comprobante.cliente_id)
        .order_by(MovimientoBanco.fecha.desc(), MovimientoBanco.id)
    ).all()

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Extracto conciliado"

    hoja.append([nombre for nombre, _ in COLUMNAS])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = ENCABEZADO
        celda.alignment = Alignment(vertical="center", wrap_text=True)
    hoja.freeze_panes = "A2"

    for numero, (ancho) in enumerate([ancho for _, ancho in COLUMNAS], start=1):
        hoja.column_dimensions[get_column_letter(numero)].width = ancho

    for movimiento, comprobante, cliente in filas:
        texto, color = _certeza(comprobante.confianza if comprobante else None)
        hoja.append([
            movimiento.cuenta,
            movimiento.hoja,
            movimiento.fila,
            movimiento.fecha,
            movimiento.nro_transaccion,
            movimiento.descripcion,
            movimiento.importe,
            "SÍ" if comprobante else "NO",
            texto,
            # El nombre del archivo, sin la carpeta del cliente: es lo que sirve
            # para buscarlo, y la carpeta ya está implícita en la columna Cliente.
            comprobante.archivo.split("/")[-1] if comprobante else None,
            cliente.nombre_completo if cliente else None,
        ])
        for celda in hoja[hoja.max_row]:
            celda.fill = color
        hoja.cell(hoja.max_row, 4).number_format = "DD/MM/YYYY"
        hoja.cell(hoja.max_row, 7).number_format = '#,##0.00'

    hoja.auto_filter.ref = hoja.dimensions

    buffer = BytesIO()
    libro.save(buffer)
    return buffer.getvalue()
