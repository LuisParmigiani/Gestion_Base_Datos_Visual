"""Parser del extracto del banco. Lógica pura: no toca la base ni la red.

Porteo de `web/src/lib/extracto.ts`, que está probado contra el extracto real de
2822 movimientos. **Los 34 tests se portaron primero** (`tests/test_extracto.py`)
y son la vara: si pasan, este archivo hace lo mismo que el original.

Se portó en vez de llamar al de TypeScript para que el producto no dependa de
`web/`, que es la herramienta con la que se midió la IA y algún día se apaga.
"""

import hashlib
import math
import re
from datetime import date, datetime, timedelta
from typing import NamedTuple

# El día 0 de los seriales de Excel. No es 1900-01-01: Excel arrastra el bug de
# creer que 1900 fue bisiesto, y esta base ya lo compensa.
ORIGEN_EXCEL = date(1899, 12, 30)

# ponytail: el rango de seriales cubre 1954-2146. Fuera de eso la celda no era
# una fecha, no es una transferencia del siglo XXII.
SERIAL_MINIMO, SERIAL_MAXIMO = 20_000, 90_000

CUIT = re.compile(r"(?<!\d)(?:20|23|24|27|30|33|34)\d{9}(?!\d)")
COELSA = re.compile(r"(?:TRANSF|CREDIN):\s*([A-Z0-9]{20,24})")

# Del más largo al más corto: si no, 'TRANSF' le ganaría a 'ING TRANSF'.
TIPOS = sorted(
    ["ING TRANSF", "TRANSF", "TEF", "CCERR", "CREDIN", "DEBIN", "IMP.", "IIBB",
     "AFIP", "AGUAS", "EPE", "MOVISTAR", "TASAS", "MUN", "CAPITALIZACION"],
    key=len,
    reverse=True,
)


class Importe(NamedTuple):
    importe: str | None
    es_ingreso: bool
    ambiguo: bool


def parsear_importe(crudo: str) -> Importe:
    """El extracto trae dos formatos mezclados en la misma columna:
    `$ 368.500,00` (argentino) y `$ 16,000.00` (estadounidense).

    Devuelve el importe como **string**, nunca como float: `0.1 + 0.2 != 0.3` y
    esto es plata. Lo recibe `NUMERIC(14,2)` de Postgres.

    Cuando no se puede saber, devuelve `ambiguo=True` e `importe=None`. **No
    adivina: un importe inventado es una acusación falsa.**
    """
    es_ingreso = "-" not in crudo
    ambiguo = Importe(None, es_ingreso, True)
    signo = "" if es_ingreso else "-"

    limpio = re.sub(r"[^\d.,]", "", crudo)
    if not any(c.isdigit() for c in limpio):
        return ambiguo

    puntos = limpio.count(".")
    comas = limpio.count(",")
    if not puntos and not comas:
        return Importe(signo + limpio, es_ingreso, False)

    # El decimal es el separador que aparece más a la derecha. El otro es de miles.
    decimal = "." if limpio.rfind(".") > limpio.rfind(",") else ","
    miles = "," if decimal == "." else "."
    veces_decimal = puntos if decimal == "." else comas
    veces_miles = comas if decimal == "." else puntos

    # Un solo tipo de separador, repetido: no puede ser decimal —un número tiene
    # un solo punto decimal— así que son todos de miles. `1.234.567` = 1234567.
    if not veces_miles and veces_decimal > 1:
        return Importe(signo + limpio.replace(decimal, ""), es_ingreso, False)

    # Los dígitos que siguen al último separador deciden. Tres dígitos es el caso
    # que no se puede resolver: `$ 1.500` puede ser 1500 o 1,50.
    detras = len(limpio) - limpio.rfind(decimal) - 1
    if detras < 1 or detras > 2 or veces_decimal > 1:
        return ambiguo

    return Importe(
        signo + limpio.replace(miles, "").replace(decimal, "."), es_ingreso, False
    )


def fecha_de_celda(valor) -> str | None:
    """Fecha de una celda del extracto, como `YYYY-MM-DD`.

    Acepta una fecha ya parseada por la librería de Excel o un serial crudo. La
    hora se descarta siempre: un día corrido rompería el cruce por fecha.
    """
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    # bool es subclase de int en Python, y `True` no es una fecha.
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    if math.isnan(valor) or math.isinf(valor):
        return None
    if valor < SERIAL_MINIMO or valor > SERIAL_MAXIMO:
        return None
    return (ORIGEN_EXCEL + timedelta(days=math.floor(valor))).isoformat()


def extraer_cuit(descripcion: str) -> str | None:
    """CUIT embebido en la descripción. La clave de cruce principal."""
    encontrado = CUIT.search(descripcion)
    return encontrado.group(0) if encontrado else None


def extraer_coelsa(descripcion: str) -> str | None:
    """ID COELSA. Solo ~3% de las filas lo trae, pero da certeza total."""
    encontrado = COELSA.search(descripcion)
    return encontrado.group(1) if encontrado else None


def extraer_tipo(descripcion: str) -> str | None:
    """Tipo de movimiento según el prefijo de la descripción."""
    return next((t for t in TIPOS if descripcion.startswith(t)), None)


def huella(
    *, cuenta: str, fecha: str, nro: str, importe_crudo: str, descripcion: str
) -> str:
    """La huella que deduplica, como UNIQUE en la base.

    Usa `importe_crudo` y no el importe parseado: las filas ambiguas tienen
    importe NULL y colisionarían todas entre sí.
    """
    campos = [cuenta, fecha, nro, importe_crudo, descripcion]
    return hashlib.sha256(" ".join(campos).encode()).hexdigest()
