"""Crea las tablas del portal y las llena con clientes inventados.

    ia/.venv/bin/python -m portal.sembrar              # crea y siembra si está vacía
    ia/.venv/bin/python -m portal.sembrar --reiniciar  # borra todo y siembra de cero

Los datos son inventados a propósito: nombres, CUIT y montos fabricados. Ningún
dato real de nadie entra acá.
"""

import argparse
import random
from datetime import date, timedelta
from decimal import Decimal

from portal import archivos
from portal.db import Sesion, motor
from portal.modelos import Base, Cliente, registrar_movimiento

CLIENTES = [
    ("Marisa", "Quiroga", "marisa.quiroga@ejemplo.test", "27-31456789-4"),
    ("Aníbal", "Ferreyra", "anibal.ferreyra@ejemplo.test", "20-28765432-1"),
    ("Lorena", "Bustamante", "lorena.bustamante@ejemplo.test", "27-33210987-8"),
    ("Ezequiel", "Paniagua", "ezequiel.paniagua@ejemplo.test", "20-35678901-2"),
    ("Rocío", "Villalba", "rocio.villalba@ejemplo.test", "27-29876543-6"),
    ("Hernán", "Castagnino", "hernan.castagnino@ejemplo.test", "20-30112233-9"),
]

ACREDITACIONES = ["Transferencia acreditada", "Pago recibido", "Depósito acreditado"]
CONSUMOS = ["Compra — remito {n}", "Mercadería — pedido {n}", "Servicio — orden {n}"]


def sembrar(reiniciar: bool, forzar: bool = False) -> None:
    if reiniciar and not forzar:
        # `--reiniciar` hace drop_all. El 15-ago se llevó puesto un comprobante
        # que había subido una persona: el archivo quedó en disco y su fila
        # desapareció, así que en la pantalla dejó de existir sin dejar rastro.
        # Los datos inventados se rehacen; lo que subió alguien, no.
        subidos = [a for a in archivos.CARPETA.rglob("*") if a.is_file()]
        if subidos:
            raise SystemExit(
                f"\nHay {len(subidos)} comprobante(s) subidos en {archivos.CARPETA}.\n"
                "`--reiniciar` borra las tablas y esas filas no se pueden reconstruir.\n"
                "Si es a propósito, agregá --forzar. Para cambiar el esquema sin perder\n"
                "nada, usá un ALTER TABLE.\n"
            )
    if reiniciar:
        Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)

    azar = random.Random(2026)
    hoy = date.today()

    with Sesion() as sesion:
        if sesion.query(Cliente).count():
            print("La base ya tiene clientes. Usá --reiniciar para rehacerla.")
            return

        for nombre, apellido, email, cuit in CLIENTES:
            cliente = Cliente(nombre=nombre, apellido=apellido, email=email, cuit=cuit)
            sesion.add(cliente)

            # Entre 4 y 9 movimientos repartidos en los últimos 6 meses.
            for _ in range(azar.randint(4, 9)):
                fecha = hoy - timedelta(days=azar.randint(1, 180))
                if azar.random() < 0.55:
                    concepto = azar.choice(ACREDITACIONES)
                    monto = Decimal(azar.randrange(15_000, 250_000, 500))
                else:
                    concepto = azar.choice(CONSUMOS).format(n=azar.randint(1000, 9999))
                    monto = -Decimal(azar.randrange(5_000, 180_000, 500))
                registrar_movimiento(sesion, cliente, fecha, concepto, monto)

        sesion.commit()

        for cliente in sesion.query(Cliente).order_by(Cliente.id):
            print(f"  {cliente.id}  {cliente.nombre_completo:<24} saldo {cliente.saldo:>12,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reiniciar", action="store_true", help="borra las tablas y siembra de cero")
    parser.add_argument("--forzar", action="store_true",
                        help="reinicia aunque haya comprobantes subidos. Se pierden")
    args = parser.parse_args()
    sembrar(args.reiniciar, args.forzar)
