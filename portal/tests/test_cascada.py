"""La cascada de cruce: lógica pura, sin base y sin IA.

Es el componente donde un error silencioso acusa a un cliente honesto, así que
va con TDD, como manda `CLAUDE.md`. Los casos vienen de la cascada medida en
`web/src/lib/eleccion.ts`, que acierta 29 de 30 cuando propone un solo candidato.
"""

import unittest
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from portal.cascada import candidatos, fecha_de_texto, monto_de_texto, solo_digitos


class Fila(NamedTuple):
    """Un movimiento del banco, con lo mínimo que mira la cascada."""

    id: int
    fecha: date
    importe: Decimal | None = None
    nro_transaccion: str | None = None
    cuit_emisor: str | None = None
    es_ingreso: bool = True
    comprobante_id: int | None = None


DIA = date(2026, 8, 15)


def leido(**campos) -> dict:
    """Lo que devolvió la IA. Los 16 campos, pero solo importan estos cuatro."""
    return {"monto": None, "fecha": None, "cuit_emisor": None, "referencia": None, **campos}


class Normalizadores(unittest.TestCase):
    def test_el_cuit_se_compara_por_sus_digitos(self):
        # El extracto lo trae sin separadores y una persona lo escribe con
        # guiones. Comparar los textos tal cual dejaba 33 comprobantes sin cruzar.
        self.assertEqual(solo_digitos("27-31456789-4"), "27314567894")
        self.assertEqual(solo_digitos("27314567894"), "27314567894")

    def test_un_cuit_vacio_no_es_un_cuit(self):
        self.assertIsNone(solo_digitos(""))
        self.assertIsNone(solo_digitos(None))
        self.assertIsNone(solo_digitos("sin dígitos"))

    def test_el_monto_cruza_en_los_dos_formatos(self):
        # La IA escribe el monto como lo ve, y ahí conviven los dos formatos.
        self.assertEqual(monto_de_texto("$ 12.345,60"), Decimal("12345.60"))
        self.assertEqual(monto_de_texto("12,345.60"), Decimal("12345.60"))
        self.assertEqual(monto_de_texto("12345.60"), Decimal("12345.60"))

    def test_un_monto_ambiguo_no_se_adivina(self):
        self.assertIsNone(monto_de_texto("$ 1.500"))
        self.assertIsNone(monto_de_texto(""))
        self.assertIsNone(monto_de_texto(None))

    def test_la_fecha_se_entiende_en_los_formatos_que_escribe_la_ia(self):
        for texto in ["2026-08-15", "15/08/2026", "15-08-2026"]:
            self.assertEqual(fecha_de_texto(texto), DIA, texto)

    def test_una_fecha_que_no_se_entiende_no_se_inventa(self):
        self.assertIsNone(fecha_de_texto("ayer"))
        self.assertIsNone(fecha_de_texto(""))
        self.assertIsNone(fecha_de_texto(None))
        self.assertIsNone(fecha_de_texto("32/13/2026"))


class Escalones(unittest.TestCase):
    def test_escalon_1_nro_de_transaccion_mas_cuit_da_90(self):
        filas = [Fila(1, DIA, nro_transaccion="ABC123", cuit_emisor="27314567894")]
        encontrados = candidatos(
            leido(referencia="ABC123", cuit_emisor="27-31456789-4"), filas
        )
        self.assertEqual(encontrados, [(1, 90)])

    def test_el_nro_de_transaccion_no_distingue_mayusculas(self):
        # Puede traer letras y la IA las transcribe como las ve.
        filas = [Fila(1, DIA, nro_transaccion="abc123", cuit_emisor="27314567894")]
        encontrados = candidatos(
            leido(referencia="ABC123", cuit_emisor="27314567894"), filas
        )
        self.assertEqual(encontrados, [(1, 90)])

    def test_escalon_2_cuit_mas_monto_mas_fecha_da_90(self):
        filas = [Fila(1, DIA, importe=Decimal("12345.60"), cuit_emisor="27314567894")]
        encontrados = candidatos(
            leido(monto="$ 12.345,60", fecha="15/08/2026", cuit_emisor="27314567894"),
            filas,
        )
        self.assertEqual(encontrados, [(1, 90)])

    def test_escalon_3_monto_mas_fecha_da_50_y_solo_si_se_habilita(self):
        filas = [Fila(1, DIA, importe=Decimal("12345.60"))]
        leidos = leido(monto="12345.60", fecha="2026-08-15")

        self.assertEqual(candidatos(leidos, filas, incluir_50=True), [(1, 50)])
        self.assertEqual(candidatos(leidos, filas), [])

    def test_el_escalon_3_no_mira_egresos(self):
        # Un pago de un cliente es plata entrando. Un egreso no puede ser suyo.
        filas = [Fila(1, DIA, importe=Decimal("100"), es_ingreso=False)]
        encontrados = candidatos(
            leido(monto="100", fecha="2026-08-15"), filas, incluir_50=True
        )
        self.assertEqual(encontrados, [])

    def test_un_escalon_alto_deja_afuera_a_los_de_abajo(self):
        # La misma fila cruza por los tres. Tiene que aparecer una sola vez, al 90.
        filas = [Fila(1, DIA, importe=Decimal("100"),
                      nro_transaccion="X1", cuit_emisor="27314567894")]
        encontrados = candidatos(
            leido(monto="100", fecha="2026-08-15", cuit_emisor="27314567894",
                  referencia="X1"),
            filas,
            incluir_50=True,
        )
        self.assertEqual(encontrados, [(1, 90)])

    def test_sin_datos_para_cruzar_no_devuelve_nada(self):
        filas = [Fila(1, DIA, importe=Decimal("100"), cuit_emisor="27314567894")]
        self.assertEqual(candidatos(leido(), filas, incluir_50=True), [])

    def test_dos_filas_que_cruzan_igual_vuelven_las_dos(self):
        # Dos transferencias del mismo monto el mismo día. La cascada NO elige:
        # decide el dueño. Adivinar entre dos filas iguales sería inventar.
        filas = [
            Fila(1, DIA, importe=Decimal("100")),
            Fila(2, DIA, importe=Decimal("100")),
        ]
        encontrados = candidatos(
            leido(monto="100", fecha="2026-08-15"), filas, incluir_50=True
        )
        self.assertEqual(encontrados, [(1, 50), (2, 50)])

    def test_una_fila_ya_tomada_igual_se_devuelve(self):
        # No se esconde: que cruce con una fila tomada es exactamente la señal
        # de disputa, y esconderla dejaría al comprobante sin explicación.
        filas = [Fila(1, DIA, importe=Decimal("100"), comprobante_id=99)]
        encontrados = candidatos(
            leido(monto="100", fecha="2026-08-15"), filas, incluir_50=True
        )
        self.assertEqual(encontrados, [(1, 50)])

    def test_un_monto_ambiguo_del_extracto_no_cruza_con_nada(self):
        # importe NULL es "no se pudo saber", no "coincide con lo que sea".
        filas = [Fila(1, DIA, importe=None)]
        encontrados = candidatos(
            leido(monto="100", fecha="2026-08-15"), filas, incluir_50=True
        )
        self.assertEqual(encontrados, [])


if __name__ == "__main__":
    unittest.main()
