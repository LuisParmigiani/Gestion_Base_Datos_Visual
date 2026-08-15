"""Pruebas del lote: los cinco desenlaces, el CBU propio y la guarda de arranque.

La IA se reemplaza por un doble (`lote.leer`) que devuelve campos fijos. No es
un mock que finge que algo anda: lo que se prueba acá es la LÓGICA del lote —qué
hace con lo que le den— y esa lógica es todo lo que puede acusar a un cliente
honesto. Lo que el modelo lee de verdad se mide aparte, contra la vara de 16.
"""

import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from portal import archivos, lote
from portal.db import Sesion, motor
from portal.modelos import (
    CONFIRMADO,
    EN_DISPUTA,
    PENDIENTE,
    REVISION_MANUAL,
    Base,
    CbuPropio,
    Cliente,
    Comprobante,
    Extraccion,
    MovimientoBanco,
    MovimientoCuenta,
)

if not str(motor.url).endswith("portal_test"):
    raise SystemExit(
        f"Los tests apuntan a {motor.url!r}. Falta PORTAL_DATABASE_URL con portal_test."
    )

CBU_PROPIO = "0170099220000012345678"
DIA = date(2026, 8, 15)


def campos(**cambios) -> dict:
    """Lo que devolvería la IA para un comprobante que cae en la cuenta del dueño."""
    return {
        "monto": "12.345,60", "fecha": "15/08/2026",
        "cuit_emisor": "27-31456789-4", "referencia": None,
        "cbu_cvu_receptor": CBU_PROPIO, "cuit_receptor": None,
        **cambios,
    }


class LoteBase(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(motor)
        Base.metadata.create_all(motor)

        self.carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta.cleanup)
        original = archivos.CARPETA
        archivos.CARPETA = Path(self.carpeta.name)
        self.addCleanup(setattr, archivos, "CARPETA", original)

        leer_original = lote.leer
        self.addCleanup(setattr, lote, "leer", leer_original)

        with Sesion() as sesion:
            sesion.add(Cliente(nombre="Ana", apellido="Test", email="ana@test.test"))
            sesion.add(CbuPropio(valor=CBU_PROPIO, aprobado_en=datetime.now()))
            sesion.commit()

    def con_lecturas(self, *por_intento):
        """Hace que la IA devuelva estos campos, uno por intento (variante)."""
        intentos = iter(por_intento)

        def doble(rutas):
            campos_ = next(intentos)
            return [{"campos": campos_} for _ in rutas]

        lote.leer = doble

    def comprobante(self, cliente_id=1) -> int:
        imagen = Path(self.carpeta.name) / "c.jpg"
        Image.new("RGB", (60, 40), "white").save(imagen)
        with Sesion() as sesion:
            fila = Comprobante(cliente_id=cliente_id, archivo="c.jpg", estado=PENDIENTE)
            sesion.add(fila)
            sesion.commit()
            return fila.id

    def fila_banco(self, **cambios) -> int:
        datos = {
            "cuenta": "SUCESION", "fecha": DIA, "descripcion": "ING TRANSF X",
            "importe_crudo": "$ 12.345,60", "importe": Decimal("12345.60"),
            "es_ingreso": True, "cuit_emisor": "27314567894",
            "huella": f"h{cambios.get('huella_extra', '')}",
            **{k: v for k, v in cambios.items() if k != "huella_extra"},
        }
        with Sesion() as sesion:
            fila = MovimientoBanco(**datos)
            sesion.add(fila)
            sesion.commit()
            return fila.id

    def recargar(self, id_):
        with Sesion() as sesion:
            return sesion.get(Comprobante, id_)


class Desenlaces(LoteBase):
    def test_cruza_al_90_confirma_suma_el_saldo_y_toma_la_fila(self):
        id_comprobante = self.comprobante()
        id_fila = self.fila_banco()
        self.con_lecturas(campos())

        resumen = lote.correr()

        self.assertEqual(resumen[CONFIRMADO], 1)
        with Sesion() as sesion:
            self.assertEqual(sesion.get(Comprobante, id_comprobante).estado, CONFIRMADO)
            # La fila del extracto queda marcada: nadie más puede reclamarla.
            self.assertEqual(sesion.get(MovimientoBanco, id_fila).comprobante_id,
                             id_comprobante)
            # El saldo subió por el importe DEL EXTRACTO, no por lo que leyó la IA.
            self.assertEqual(sesion.get(Cliente, 1).saldo, Decimal("12345.60"))
            movimiento = sesion.scalars(select(MovimientoCuenta)).one()
            self.assertEqual(movimiento.comprobante_id, id_comprobante)

    def test_una_fila_ya_tomada_deja_al_segundo_en_disputa(self):
        self.fila_banco()
        self.con_lecturas(campos())
        self.comprobante()
        lote.correr()  # el primero se queda con la fila

        segundo = self.comprobante()
        self.con_lecturas(campos())
        lote.correr()

        comprobante = self.recargar(segundo)
        self.assertEqual(comprobante.estado, EN_DISPUTA)
        self.assertIn("ya está asignada", comprobante.motivo)
        # Y el saldo NO se movió dos veces por la misma transferencia.
        with Sesion() as sesion:
            self.assertEqual(sesion.get(Cliente, 1).saldo, Decimal("12345.60"))

    def test_dos_filas_que_coinciden_no_se_adivinan(self):
        self.fila_banco(huella_extra="1", cuit_emisor=None)
        self.fila_banco(huella_extra="2", cuit_emisor=None)
        id_comprobante = self.comprobante()
        self.con_lecturas(*[campos(cuit_emisor=None)] * 3)

        lote.correr(incluir_50=True)

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, REVISION_MANUAL)
        self.assertIn("2 filas", comprobante.motivo)

    def test_sin_cruce_y_con_el_dia_cargado_va_a_revision(self):
        self.fila_banco(importe=Decimal("999.99"))  # ese día existe, la fila no
        id_comprobante = self.comprobante()
        self.con_lecturas(*[campos()] * 3)

        lote.correr()

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, REVISION_MANUAL)
        self.assertIn("está cargado en el extracto", comprobante.motivo)
        self.assertEqual(comprobante.intentos, 3)

    def test_sin_cruce_y_sin_ese_dia_sigue_pendiente(self):
        self.fila_banco(fecha=date(2026, 1, 1), importe=Decimal("999.99"))
        id_comprobante = self.comprobante()
        self.con_lecturas(*[campos()] * 3)

        lote.correr()

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, PENDIENTE)
        self.assertIn("Todavía no hay movimientos", comprobante.motivo)

    def test_si_la_fecha_cambia_entre_lecturas_no_se_da_por_buena(self):
        self.fila_banco(importe=Decimal("999.99"))
        id_comprobante = self.comprobante()
        self.con_lecturas(
            campos(fecha="15/08/2026"),
            campos(fecha="15/08/2023"),
            campos(fecha="18/08/2026"),
        )

        lote.correr()

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, REVISION_MANUAL)
        self.assertIn("no se sostiene", comprobante.motivo)


class Receptor(LoteBase):
    def test_un_cbu_ajeno_que_se_sostiene_se_le_pregunta_al_dueno(self):
        self.fila_banco()
        id_comprobante = self.comprobante()
        ajeno = "1234567890123456789012"
        self.con_lecturas(*[campos(cbu_cvu_receptor=ajeno)] * 3)

        lote.correr()

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, REVISION_MANUAL)
        self.assertIn(ajeno, comprobante.motivo)
        self.assertIn("¿Es una cuenta tuya nueva?", comprobante.motivo)
        # Y NO se acreditó nada: la plata pudo haber ido a cualquier lado.
        with Sesion() as sesion:
            self.assertEqual(sesion.get(Cliente, 1).saldo, Decimal("0.00"))

    def test_un_cbu_ajeno_distinto_en_cada_lectura_no_se_le_atribuye_a_nadie(self):
        self.fila_banco()
        id_comprobante = self.comprobante()
        self.con_lecturas(
            campos(cbu_cvu_receptor="1111111111111111111111"),
            campos(cbu_cvu_receptor="2222222222222222222222"),
            campos(cbu_cvu_receptor="3333333333333333333333"),
        )

        lote.correr()

        comprobante = self.recargar(id_comprobante)
        self.assertEqual(comprobante.estado, REVISION_MANUAL)
        self.assertNotIn("cuenta tuya nueva", comprobante.motivo)

    def test_sin_ningun_cbu_propio_el_lote_no_arranca(self):
        with Sesion() as sesion:
            sesion.query(CbuPropio).delete()
            sesion.commit()
        self.comprobante()

        with self.assertRaises(lote.SinCbuPropio):
            lote.correr()


class Evidencia(LoteBase):
    def test_cada_intento_deja_su_extraccion_guardada(self):
        self.fila_banco(importe=Decimal("999.99"))
        self.comprobante()
        self.con_lecturas(*[campos()] * 3)

        lote.correr()

        with Sesion() as sesion:
            extracciones = sesion.scalars(
                select(Extraccion).order_by(Extraccion.intento)
            ).all()
            self.assertEqual([e.intento for e in extracciones], [1, 2, 3])
            self.assertEqual([e.variante for e in extracciones],
                             ["original", "contraste", "escala"])
            self.assertEqual(extracciones[0].adaptador, "lora_v4_v2")

    def test_frena_apenas_resuelve_y_no_gasta_los_tres_intentos(self):
        self.fila_banco()
        self.comprobante()
        self.con_lecturas(campos())

        lote.correr()

        with Sesion() as sesion:
            self.assertEqual(len(sesion.scalars(select(Extraccion)).all()), 1)


if __name__ == "__main__":
    unittest.main()


class Variantes(unittest.TestCase):
    """Las tres imágenes que ve el modelo. Acá murió la primera corrida real."""

    def setUp(self):
        self.taller = tempfile.TemporaryDirectory()
        self.addCleanup(self.taller.cleanup)

    def _imagen(self, ancho, alto) -> Path:
        ruta = Path(self.taller.name) / f"{ancho}x{alto}.jpg"
        Image.new("RGB", (ancho, alto), "white").save(ruta)
        return ruta

    def _variar(self, origen, variante) -> Image.Image:
        salida = lote.variar(origen, variante, Path(self.taller.name) / f"{variante}.jpg")
        return Image.open(salida)

    def test_ninguna_variante_se_pasa_del_tope_de_tokens(self):
        # Una foto de celular vertical: 4653 tokens en original, y al 1,5× eran
        # 10430, con los que mlx pedía 57 GB y el proceso moría.
        grande = self._imagen(1320, 2782)
        for variante in lote.VARIANTES:
            with self._variar(grande, variante) as imagen:
                self.assertLessEqual(
                    lote.tokens_de(imagen), lote.TOKENS_MAXIMOS, variante
                )

    def test_la_variante_escala_ve_OTRA_resolucion_que_la_original(self):
        # Con temperature=0.0 el modelo es determinista: dos imágenes iguales dan
        # dos lecturas iguales, y la relectura no significa nada.
        for medidas in [(1320, 2782), (400, 300)]:
            origen = self._imagen(*medidas)
            with self._variar(origen, "original") as una, \
                 self._variar(origen, "escala") as otra:
                self.assertNotEqual(una.size, otra.size, f"{medidas} quedó igual")

    def test_una_imagen_chica_se_agranda_hasta_el_tope(self):
        with self._variar(self._imagen(400, 300), "escala") as imagen:
            self.assertGreater(lote.tokens_de(imagen), 150)
            self.assertLessEqual(lote.tokens_de(imagen), lote.TOKENS_MAXIMOS)


class FallosVisibles(LoteBase):
    """Un lote que se cae tiene que DECIRLO. Antes moría callado en segundo plano."""

    def test_si_la_lectura_falla_queda_el_error_a_la_vista(self):
        self.comprobante()

        def revienta(rutas):
            raise lote.FalloDeLectura("`extraer.py` terminó con código 1. metal::malloc")

        lote.leer = revienta
        lote.correr()

        self.assertIn("metal::malloc", lote.ESTADO["error"])
        comprobante = self.recargar(1)
        self.assertIn("La lectura falló", comprobante.motivo)
        self.assertIn("original", comprobante.motivo)

    def test_lo_ya_leido_sobrevive_a_un_fallo_posterior(self):
        # Leer cuesta minutos de modelo: que reviente la tercera variante no
        # puede borrar las dos lecturas que ya salieron.
        self.fila_banco(importe=Decimal("999.99"))
        self.comprobante()
        intentos = iter([campos(), campos()])

        def dos_y_revienta(rutas):
            try:
                return [{"campos": next(intentos)} for _ in rutas]
            except StopIteration:
                raise lote.FalloDeLectura("se cayó en la tercera") from None

        lote.leer = dos_y_revienta
        lote.correr()

        with Sesion() as sesion:
            guardadas = sesion.scalars(select(Extraccion)).all()
            self.assertEqual(len(guardadas), 2, "se perdieron las lecturas buenas")

    def test_sin_cbu_propio_el_motivo_queda_en_el_estado(self):
        with Sesion() as sesion:
            sesion.query(CbuPropio).delete()
            sesion.commit()
        self.comprobante()

        with self.assertRaises(lote.SinCbuPropio):
            lote.correr()
        self.assertIn("CBU propio", lote.ESTADO["error"])


class Diagnostico(LoteBase):
    """El «¿por qué está así?» que ve el dueño."""

    def test_sin_lecturas_lo_dice_en_vez_de_callarse(self):
        id_ = self.comprobante()
        with Sesion() as sesion:
            pasos = lote.diagnostico(sesion, sesion.get(Comprobante, id_))
        self.assertEqual(pasos[0]["estado"], "falla")
        self.assertIn("todavía no lo leyó", pasos[0]["detalle"])

    def test_explica_que_el_receptor_no_es_tuyo(self):
        self.fila_banco()
        id_ = self.comprobante()
        self.con_lecturas(*[campos(cbu_cvu_receptor="9999999999999999999999")] * 3)
        lote.correr()

        with Sesion() as sesion:
            pasos = {p["paso"]: p for p in
                     lote.diagnostico(sesion, sesion.get(Comprobante, id_))}
        self.assertEqual(pasos["Receptor"]["estado"], "falla")
        self.assertIn("9999999999999999999999", pasos["Receptor"]["detalle"])

    def test_avisa_cuando_la_fecha_cambio_entre_lecturas(self):
        self.fila_banco(importe=Decimal("999.99"))
        id_ = self.comprobante()
        self.con_lecturas(campos(fecha="15/08/2026"), campos(fecha="15/08/2023"),
                          campos(fecha="18/08/2026"))
        lote.correr()

        with Sesion() as sesion:
            pasos = {p["paso"]: p for p in
                     lote.diagnostico(sesion, sesion.get(Comprobante, id_))}
        self.assertEqual(pasos["Qué entendió"]["estado"], "falla")
        self.assertIn("cambió entre lecturas", pasos["Qué entendió"]["detalle"])

    def test_dice_que_el_dia_no_esta_cargado_en_el_extracto(self):
        self.fila_banco(fecha=date(2026, 1, 1), importe=Decimal("999.99"))
        id_ = self.comprobante()
        self.con_lecturas(*[campos()] * 3)
        lote.correr()

        with Sesion() as sesion:
            pasos = {p["paso"]: p for p in
                     lote.diagnostico(sesion, sesion.get(Comprobante, id_))}
        self.assertIn("No hay ningún movimiento", pasos["El día en el extracto"]["detalle"])


class CorrerDosVeces(LoteBase):
    """Correr el lote dos veces deja dos series de intentos. No puede duplicar nada."""

    def devolver_al_lote(self, id_):
        """Como cuando el dueño lo manda de vuelta, o deshace una carga."""
        with Sesion() as sesion:
            comprobante = sesion.get(Comprobante, id_)
            comprobante.estado, comprobante.intentos = PENDIENTE, 0
            sesion.commit()

    def test_la_lista_de_comprobantes_no_lo_muestra_dos_veces(self):
        from fastapi.testclient import TestClient
        from portal.app import app

        self.fila_banco(importe=Decimal("999.99"))  # no cruza: se gastan los 3 intentos
        id_ = self.comprobante()
        self.con_lecturas(*[campos()] * 3)
        lote.correr()
        self.devolver_al_lote(id_)
        self.con_lecturas(*[campos()] * 3)
        lote.correr()

        with Sesion() as sesion:
            # Dos corridas completas: 6 extracciones, con el intento 3 repetido.
            self.assertEqual(len(sesion.scalars(select(Extraccion)).all()), 6)

        pagina = TestClient(app).get("/admin/comprobantes").text
        self.assertEqual(pagina.count("¿por qué? →"), 1, "el comprobante sale duplicado")

    def test_el_diagnostico_mira_solo_la_ultima_corrida(self):
        self.fila_banco(importe=Decimal("999.99"))
        id_ = self.comprobante()
        self.con_lecturas(*[campos(fecha="01/01/2020")] * 3)
        lote.correr()
        self.devolver_al_lote(id_)
        self.con_lecturas(*[campos(fecha="15/08/2026")] * 3)
        lote.correr()

        with Sesion() as sesion:
            self.assertEqual(len(lote.ultimas_lecturas(sesion, id_)), 3)
            pasos = {p["paso"]: p for p in
                     lote.diagnostico(sesion, sesion.get(Comprobante, id_))}
        # Mezclar corridas diría "la fecha cambió", y sería mentira: dentro de la
        # última corrida la fecha salió igual las tres veces.
        self.assertEqual(pasos["Qué entendió"]["estado"], "info")
        self.assertNotIn("cambió entre lecturas", pasos["Qué entendió"]["detalle"])
