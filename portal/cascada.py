"""La cascada que decide qué fila del extracto es la de un comprobante.

**Vive acá y en ningún otro lado.** Tenerla escrita dos veces garantiza que el
día que se toque una, la otra siga diciendo lo contrario y nadie se entere hasta
que un comprobante quede mal asignado.

    1. nro de transacción + CUIT   → 90%
    2. CUIT + monto + fecha        → 90%
    3. monto + fecha (ingresos)    → 50%   ← solo si el dueño lo habilita

Porteo de `web/src/lib/eleccion.ts:candidatos()`, que está medida contra 37
elecciones humanas: **29 aciertos de 30 cuando propone un solo candidato**.

Lógica pura: no toca la base, no toca la IA, no toca el disco.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

from portal.extracto import parsear_importe

# Los formatos en los que la IA escribe una fecha. El primero que entre gana.
FORMATOS_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def solo_digitos(valor: str | None) -> str | None:
    """El CUIT/CBU por sus dígitos, que es como se compara.

    El extracto los trae sin separadores (2586 de 2586) y una persona los escribe
    con guiones (33 de 42). Comparar los textos tal cual dejaba **33 comprobantes
    sin poder cruzar nunca**; con este solo cambio el cruce por CUIT pasó de 8
    a 40. ⛔ No se aplica a `coelsa_id` ni a `referencia`: son alfanuméricos.
    """
    if not valor:
        return None
    return re.sub(r"\D", "", valor) or None


def monto_de_texto(valor: str | None) -> Decimal | None:
    """El monto que escribió la IA, como Decimal.

    Pasa por el mismo parser que el extracto: la IA escribe el número **como lo
    ve**, y ahí conviven el formato argentino y el estadounidense. Un monto
    ambiguo devuelve None y no cruza con nada — no se adivina.
    """
    if not valor:
        return None
    importe = parsear_importe(str(valor))
    if importe.importe is None:
        return None
    try:
        return Decimal(importe.importe)
    except InvalidOperation:
        return None


def fecha_de_texto(valor: str | None) -> date | None:
    """La fecha que escribió la IA. Si no se entiende, None: no se inventa."""
    if not valor:
        return None
    for formato in FORMATOS_FECHA:
        try:
            return datetime.strptime(str(valor).strip(), formato).date()
        except ValueError:
            continue
    return None


def candidatos(
    campos: dict, movimientos: Sequence, incluir_50: bool = False
) -> list[tuple[int, int]]:
    """Devuelve `(id del movimiento, confianza)` por cada fila que cruza.

    Los escalones son **excluyentes**: si una fila cruza por el 1, no se la
    vuelve a proponer por el 2 ni por el 3.

    **No elige.** Si dos filas cruzan igual, vuelven las dos y decide el dueño:
    adivinar entre dos transferencias del mismo importe el mismo día sería
    inventar. Las filas ya tomadas también vuelven — que un comprobante cruce
    con una fila de otro es justamente la señal de disputa, y esconderla lo
    dejaría sin explicación.
    """
    cuit = solo_digitos(campos.get("cuit_emisor"))
    referencia = (campos.get("referencia") or "").strip().lower() or None
    monto = monto_de_texto(campos.get("monto"))
    fecha = fecha_de_texto(campos.get("fecha"))

    encontrados: list[tuple[int, int]] = []
    resueltos: set[int] = set()

    def agregar(fila, confianza: int) -> None:
        if fila.id not in resueltos:
            resueltos.add(fila.id)
            encontrados.append((fila.id, confianza))

    # Escalón 1 · el nro de transacción respaldado por el CUIT.
    if referencia and cuit:
        for fila in movimientos:
            if (fila.nro_transaccion or "").strip().lower() == referencia and \
                    solo_digitos(fila.cuit_emisor) == cuit:
                agregar(fila, 90)

    # Escalón 2 · CUIT, importe y día, los tres a la vez. Son datos
    # independientes: que coincidan por casualidad los tres es mucho menos
    # probable que un choque de importe, así que vale lo mismo que el escalón 1.
    if cuit and monto is not None and fecha is not None:
        for fila in movimientos:
            if solo_digitos(fila.cuit_emisor) == cuit and \
                    fila.importe == monto and fila.fecha == fecha:
                agregar(fila, 90)

    # Escalón 3 · sin un CUIT que lo respalde, un importe y un día que coinciden
    # son eso y nada más: pueden ser casualidad.
    if incluir_50 and monto is not None and fecha is not None:
        for fila in movimientos:
            if fila.importe == monto and fila.fecha == fecha and fila.es_ingreso:
                agregar(fila, 50)

    return encontrados
