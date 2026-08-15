"""Los 34 tests de `web/src/lib/extracto.test.ts`, portados uno a uno.

Este archivo es la vara del porteo: si pasan todos, el parser de Python hace
exactamente lo mismo que el de TypeScript, que está probado contra el extracto
real de 2822 movimientos. Los comentarios de cada bloque vienen del original
porque explican POR QUÉ el caso existe, que es lo que no se puede reconstruir.
"""

import unittest
from datetime import datetime

from portal.extracto import (
    extraer_coelsa,
    extraer_cuit,
    extraer_tipo,
    fecha_de_celda,
    huella,
    parsear_importe,
)


class Importes(unittest.TestCase):
    """El extracto trae dos formatos de número mezclados en la misma columna.

    Un parser ingenuo lee 368.500,00 como 368,50 y no rompe nada: solo produce
    un número equivocado que después acusa a un cliente honesto.
    """

    def test_formato_argentino_el_ultimo_separador_es_el_decimal(self):
        self.assertEqual(parsear_importe("$ 368.500,00"), ("368500.00", True, False))

    def test_formato_estadounidense_el_ultimo_separador_es_el_decimal(self):
        self.assertEqual(parsear_importe("$ 16,000.00"), ("16000.00", True, False))

    def test_un_importe_negativo_es_un_egreso(self):
        self.assertEqual(parsear_importe("-$ 112,340.06"), ("-112340.06", False, False))

    def test_varios_separadores_de_miles_y_una_coma_decimal(self):
        self.assertEqual(parsear_importe("$ 5.094.237,85"), ("5094237.85", True, False))

    def test_sin_separadores(self):
        self.assertEqual(parsear_importe("$ 250000"), ("250000", True, False))

    def test_un_separador_con_dos_digitos_detras_es_un_decimal(self):
        self.assertEqual(parsear_importe("$ 1.50"), ("1.50", True, False))
        self.assertEqual(parsear_importe("$ 1,50"), ("1.50", True, False))

    def test_un_separador_con_un_digito_detras_es_un_decimal(self):
        self.assertEqual(parsear_importe("$ 1,5"), ("1.5", True, False))

    def test_un_separador_con_tres_digitos_detras_es_ambiguo_y_no_se_adivina(self):
        self.assertEqual(parsear_importe("$ 1.500"), (None, True, True))
        self.assertEqual(parsear_importe("$ 1,500"), (None, True, True))

    def test_un_ambiguo_negativo_conserva_el_signo_aunque_no_tenga_importe(self):
        self.assertEqual(parsear_importe("-$ 1.500"), (None, False, True))

    def test_dos_separadores_del_mismo_tipo_son_miles_no_ambiguedad(self):
        # Un número tiene un solo punto decimal: '1.234.567' es un millón y pico.
        self.assertEqual(parsear_importe("$ 1.234.567"), ("1234567", True, False))

    def test_una_celda_sin_digitos_no_se_inventa_queda_ambigua(self):
        self.assertEqual(parsear_importe(""), (None, True, True))

    def test_el_importe_vuelve_como_string_nunca_como_numero(self):
        # 0.1 + 0.2 != 0.3 y esto es plata. Lo recibe NUMERIC(14,2).
        self.assertIsInstance(parsear_importe("$ 368.500,00").importe, str)


class Fechas(unittest.TestCase):
    """Verificado contra el archivo real: las 2843 celdas vienen como fecha.

    El serial de Excel queda cubierto igual porque el archivo es un pegado
    manual de descargas y una podría venir cruda.
    """

    def test_una_celda_de_fecha_se_convierte_a_iso(self):
        self.assertEqual(fecha_de_celda(datetime(2026, 2, 27)), "2026-02-27")

    def test_la_fecha_no_se_corre_por_la_hora(self):
        self.assertEqual(fecha_de_celda(datetime(2026, 2, 27, 23, 59)), "2026-02-27")

    def test_un_serial_de_excel_se_convierte_a_fecha(self):
        self.assertEqual(fecha_de_celda(46080), "2026-02-27")

    def test_el_serial_con_parte_decimal_ignora_la_hora(self):
        self.assertEqual(fecha_de_celda(46080.75), "2026-02-27")

    def test_un_serial_fuera_de_rango_no_se_convierte(self):
        self.assertIsNone(fecha_de_celda(0))
        self.assertIsNone(fecha_de_celda(float("nan")))

    def test_una_celda_vacia_o_de_otro_tipo_no_inventa_una_fecha(self):
        self.assertIsNone(fecha_de_celda(None))
        self.assertIsNone(fecha_de_celda(""))
        self.assertIsNone(fecha_de_celda("27/02/2026"))


class Cuit(unittest.TestCase):
    """Embebido en la descripción. Es la clave de cruce principal."""

    def test_extrae_el_cuit_de_la_descripcion(self):
        self.assertEqual(extraer_cuit("ING TRANSF 27123456789 GOMEZ/A"), "27123456789")

    def test_acepta_los_prefijos_validos_de_cuit(self):
        for prefijo in ["20", "23", "24", "27", "30", "33", "34"]:
            self.assertEqual(
                extraer_cuit(f"TRANSF {prefijo}123456789 X"), f"{prefijo}123456789"
            )

    def test_no_confunde_un_prefijo_invalido_con_un_cuit(self):
        self.assertIsNone(extraer_cuit("TRANSF 99123456789 X"))

    def test_no_recorta_un_cuit_de_adentro_de_un_numero_mas_largo(self):
        self.assertIsNone(extraer_cuit("TRANSF 9027123456789012 X"))

    def test_sin_cuit_devuelve_none_no_string_vacio(self):
        self.assertIsNone(extraer_cuit("MOVISTAR FACTURA"))


class Coelsa(unittest.TestCase):
    """Solo el ~3% de las filas lo trae, pero cuando está es certeza total."""

    def test_extrae_el_coelsa_despues_de_transf(self):
        self.assertEqual(
            extraer_coelsa("TRANSF:ABC123DEF456GHI789JKL0-20123456789"),
            "ABC123DEF456GHI789JKL0",
        )

    def test_extrae_el_coelsa_despues_de_credin(self):
        self.assertEqual(
            extraer_coelsa("CREDIN:ABC123DEF456GHI789JKL0"), "ABC123DEF456GHI789JKL0"
        )

    def test_sin_coelsa_devuelve_none(self):
        self.assertIsNone(extraer_coelsa("ING TRANSF 27123456789 GOMEZ/A"))

    def test_un_token_demasiado_corto_no_es_un_coelsa(self):
        self.assertIsNone(extraer_coelsa("TRANSF:ABC123"))


class Tipo(unittest.TestCase):
    def test_reconoce_el_tipo_por_el_prefijo_de_la_descripcion(self):
        self.assertEqual(extraer_tipo("TEF 27123456789 X"), "TEF")
        self.assertEqual(extraer_tipo("MOVISTAR FACTURA"), "MOVISTAR")

    def test_ing_transf_gana_sobre_transf_que_es_su_prefijo(self):
        self.assertEqual(extraer_tipo("ING TRANSF 27123456789 X"), "ING TRANSF")

    def test_una_descripcion_sin_prefijo_conocido_no_inventa_un_tipo(self):
        self.assertIsNone(extraer_tipo("ALGO QUE NO ESTA EN LA LISTA"))


FILA = {
    "cuenta": "SUCESION",
    "fecha": "2026-02-27",
    "nro": "123456",
    "importe_crudo": "$ 368.500,00",
    "descripcion": "ING TRANSF 27123456789 X",
}


class Huella(unittest.TestCase):
    """Es el UNIQUE que deduplica, y lo que hace seguro reimportar el Excel.

    Usa el importe CRUDO y no el parseado: las filas ambiguas tienen importe
    NULL y colisionarían todas entre sí.
    """

    def test_la_misma_fila_da_siempre_la_misma_huella(self):
        self.assertEqual(huella(**FILA), huella(**dict(FILA)))

    def test_cambiar_cualquier_campo_cambia_la_huella(self):
        for campo in FILA:
            self.assertNotEqual(
                huella(**{**FILA, campo: "otro"}),
                huella(**FILA),
                f"cambiar {campo} no cambió la huella",
            )

    def test_dos_filas_ambiguas_distintas_no_colisionan(self):
        self.assertNotEqual(
            huella(**{**FILA, "importe_crudo": "$ 1.500"}),
            huella(**{**FILA, "importe_crudo": "$ 2.500"}),
        )


if __name__ == "__main__":
    unittest.main()
