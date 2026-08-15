"""Pruebas del portal. Corren SIEMPRE contra `portal_test`, nunca contra `portal`.

    PORTAL_DATABASE_URL=postgresql+psycopg://luisparmigiani@localhost:5432/portal_test \
      ia/.venv/bin/python -m unittest discover portal/tests -v

Sin framework, como el resto del proyecto: `unittest` es de la stdlib.
"""

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from portal import archivos
from portal.app import app
from portal.db import Sesion, motor
from portal.modelos import (
    PENDIENTE,
    Base,
    Cliente,
    Comprobante,
    MovimientoCuenta,
    registrar_movimiento,
)

# Los tests borran tablas. Si la URL no es la de test, no se corre nada.
if not str(motor.url).endswith("portal_test"):
    raise SystemExit(
        f"Los tests apuntan a {motor.url!r}. Falta PORTAL_DATABASE_URL con portal_test."
    )


def imagen_falsa() -> bytes:
    """Un JPEG válido y fabricado. Ningún comprobante real entra en los tests."""
    buffer = BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def pdf_falso() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PDF")
    return buffer.getvalue()


class BaseLimpia(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(motor)
        Base.metadata.create_all(motor)
        with Sesion() as sesion:
            sesion.add_all([
                Cliente(nombre="Ana", apellido="Test", email="ana@test.test"),
                Cliente(nombre="Beto", apellido="Test", email="beto@test.test"),
            ])
            sesion.commit()


class SaldoYLibro(BaseLimpia):
    def test_el_saldo_coincide_con_la_suma_del_libro(self):
        montos = [Decimal("15000.50"), Decimal("-4000"), Decimal("120000"), Decimal("-1.50")]
        with Sesion() as sesion:
            cliente = sesion.get(Cliente, 1)
            for monto in montos:
                registrar_movimiento(sesion, cliente, date(2026, 8, 15), "prueba", monto)
            sesion.commit()

        with Sesion() as sesion:
            cliente = sesion.get(Cliente, 1)
            suma = sesion.scalar(
                select(func.sum(MovimientoCuenta.monto)).where(MovimientoCuenta.cliente_id == 1)
            )
            self.assertEqual(cliente.saldo, sum(montos))
            self.assertEqual(cliente.saldo, suma)

    def test_un_rollback_no_deja_el_saldo_movido(self):
        with Sesion() as sesion:
            cliente = sesion.get(Cliente, 1)
            registrar_movimiento(sesion, cliente, date(2026, 8, 15), "queda", Decimal("50000"))
            sesion.commit()

        with Sesion() as sesion:
            cliente = sesion.get(Cliente, 1)
            registrar_movimiento(sesion, cliente, date(2026, 8, 15), "se cae", Decimal("99999"))
            sesion.rollback()

        with Sesion() as sesion:
            self.assertEqual(sesion.get(Cliente, 1).saldo, Decimal("50000.00"))
            self.assertEqual(sesion.scalar(select(func.count()).select_from(MovimientoCuenta)), 1)


class Subida(BaseLimpia):
    def setUp(self):
        super().setUp()
        # Los archivos de prueba no van a portal/comprobantes/.
        self.carpeta = tempfile.TemporaryDirectory()
        self.carpeta_real = archivos.CARPETA
        archivos.CARPETA = Path(self.carpeta.name)
        self.addCleanup(setattr, archivos, "CARPETA", self.carpeta_real)
        self.addCleanup(self.carpeta.cleanup)
        self.cliente_http = TestClient(app)

    def test_subir_deja_el_archivo_y_la_fila_pendiente(self):
        respuesta = self.cliente_http.post(
            "/cliente/1/subir",
            files={"archivo": ("foto.jpg", imagen_falsa(), "image/jpeg")},
            data={"fecha_declarada": "2026-08-14"},
            follow_redirects=False,
        )
        self.assertEqual(respuesta.status_code, 303)

        with Sesion() as sesion:
            comprobante = sesion.scalars(select(Comprobante)).one()
            self.assertEqual(comprobante.cliente_id, 1)
            self.assertEqual(comprobante.estado, PENDIENTE)
            self.assertEqual(comprobante.fecha_declarada, date(2026, 8, 14))
            self.assertTrue((Path(self.carpeta.name) / comprobante.archivo).exists())

    def test_un_pdf_se_guarda_convertido_a_imagen(self):
        self.cliente_http.post(
            "/cliente/1/subir",
            files={"archivo": ("recibo.pdf", pdf_falso(), "application/pdf")},
            follow_redirects=False,
        )
        with Sesion() as sesion:
            comprobante = sesion.scalars(select(Comprobante)).one()
            self.assertTrue(comprobante.archivo.endswith(".jpg"))
            guardado = Path(self.carpeta.name) / comprobante.archivo
            with Image.open(guardado) as convertida:
                self.assertEqual(convertida.format, "JPEG")

    def test_un_archivo_que_no_es_imagen_se_rechaza(self):
        respuesta = self.cliente_http.post(
            "/cliente/1/subir",
            files={"archivo": ("trucho.jpg", b"no soy una imagen", "image/jpeg")},
            follow_redirects=False,
        )
        self.assertEqual(respuesta.status_code, 400)
        with Sesion() as sesion:
            self.assertEqual(sesion.scalar(select(func.count()).select_from(Comprobante)), 0)

    def test_un_cliente_no_ve_el_comprobante_de_otro(self):
        self.cliente_http.post(
            "/cliente/1/subir",
            files={"archivo": ("foto.jpg", imagen_falsa(), "image/jpeg")},
            follow_redirects=False,
        )
        with Sesion() as sesion:
            id_comprobante = sesion.scalars(select(Comprobante)).one().id

        self.assertEqual(self.cliente_http.get(f"/cliente/1/comprobante/{id_comprobante}").status_code, 200)
        self.assertEqual(self.cliente_http.get(f"/cliente/2/comprobante/{id_comprobante}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
