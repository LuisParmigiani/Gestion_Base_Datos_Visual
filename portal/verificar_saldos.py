"""Comprueba que la columna `saldo` no se haya despegado del libro.

    ia/.venv/bin/python -m portal.verificar_saldos

El saldo está guardado en vez de calcularse en cada pantalla, y esa es la parte
frágil del modelo. Esto lo recalcula sumando `movimiento_cuenta` y avisa fila por
fila. Sale con código 1 si alguna no coincide, así puede correr desatendido.
"""

import sys

from sqlalchemy import func, select

from portal.db import Sesion
from portal.modelos import Cliente, MovimientoCuenta


def verificar() -> int:
    """Devuelve cuántos clientes tienen el saldo despegado del libro."""
    suma_del_libro = (
        select(
            MovimientoCuenta.cliente_id.label("cliente_id"),
            func.sum(MovimientoCuenta.monto).label("suma"),
        )
        .group_by(MovimientoCuenta.cliente_id)
        .subquery()
    )

    despegados = 0
    with Sesion() as sesion:
        filas = sesion.execute(
            select(Cliente, func.coalesce(suma_del_libro.c.suma, 0))
            .outerjoin(suma_del_libro, suma_del_libro.c.cliente_id == Cliente.id)
            .order_by(Cliente.id)
        )
        for cliente, suma in filas:
            if cliente.saldo == suma:
                print(f"  ✓ {cliente.id:>3}  {cliente.nombre_completo:<26} {cliente.saldo:>14,.2f}")
            else:
                despegados += 1
                print(
                    f"  ✗ {cliente.id:>3}  {cliente.nombre_completo:<26} "
                    f"columna {cliente.saldo:,.2f} · libro {suma:,.2f} "
                    f"· diferencia {cliente.saldo - suma:,.2f}"
                )

    print(
        "\nTodos los saldos coinciden con su libro."
        if not despegados
        else f"\n⚠️  {despegados} saldo(s) despegado(s) del libro."
    )
    return despegados


if __name__ == "__main__":
    sys.exit(1 if verificar() else 0)
