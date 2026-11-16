"""Troceado por literales, query según consumo atípico y descarte por premisa
(casos 252629 y 252396: mes reclamado NO atípico)."""

import unittest
from types import SimpleNamespace

from app.src.application.services.rag.legal_chunker import trocear_articulo
from app.src.application.usecase.pasos.conclusion import _historial_consumos
from app.src.application.usecase.pasos.fundamentacion import (
    CONSULTA_MES_RECLAMADO, PasoFundamentacion, premisa_no_cumplida, situacion_del_caso,
)
from app.src.core.model.informe_atencion import BloqueMedio, ProblemaNormado

LARGO = "x" * 700

ART_91 = "\n".join([
    f"a) Facturación en caso de nuevas conexiones domiciliarias: {LARGO}",
    "b) Facturación gradual si se instala el medidor por primera vez:",
    "i) Primera etapa: asignación de consumo.",
    "ii) Primera facturación.",
    f"e) no es la letra siguiente, sigue dentro de b) {LARGO}",
    "c) Facturación para conexiones con medidor no reinstalado.",
    "f) Diferencia de lecturas válida.- entre 28 y 32 días.",
])


class TestTroceadoPorLiterales(unittest.TestCase):
    def test_cada_literal_largo_es_su_chunk_y_romanos_no_abren_grupo(self):
        numerales = [c["numeral"] for c in trocear_articulo("91", ART_91)]
        self.assertEqual(numerales[0], "91 a)")
        self.assertIn("91 b)", numerales)
        # "i)" (romano) y la "e)" fuera de secuencia quedan dentro de b);
        # c) y f) son cortos y consecutivos en la secuencia aceptada (c) → se juntan.
        self.assertNotIn("91 i)", numerales)
        self.assertTrue(any(n and n.startswith("91 c)") for n in numerales))

    def test_articulo_corto_no_se_trocea_por_literales(self):
        chunks = trocear_articulo("10", "a) Uno.\nb) Dos.")
        self.assertEqual([c["numeral"] for c in chunks], [None])


def _hecho(tipo, valor=None, periodo=None):
    return ProblemaNormado(tipo=tipo, detalle=tipo, valor=valor, periodo=periodo)


def _informe(bloques):
    return SimpleNamespace(bloques=bloques)


class TestSituacionYPremisas(unittest.TestCase):
    def setUp(self):
        self.informe = _informe([
            BloqueMedio("tarjeta_lectura", "Tarjeta", {}, "", constataciones=[
                _hecho("lecturaMesReclamado", {"atipico": False}, "2026-09")]),
            BloqueMedio("record_facturacion", "Récord", {}, "", constataciones=[
                _hecho("facturacionMesReclamado", {"forma": "MEDIDO"}, "2026-09")]),
        ])

    def test_situacion_del_caso(self):
        self.assertEqual(situacion_del_caso(self.informe),
                         {"atipico": False, "con_medidor": True, "medidor_reciente": False})

    def test_query_de_mes_normal_pide_diferencia_de_lecturas_valida(self):
        situacion = situacion_del_caso(self.informe)
        q = PasoFundamentacion.construir_query(
            _hecho("facturacionMesReclamado", {"forma": "MEDIDO"}), "", situacion)
        self.assertIn(CONSULTA_MES_RECLAMADO[False], q)
        q = PasoFundamentacion.construir_query(_hecho("lecturaMesReclamado", {"atipico": True}))
        self.assertIn(CONSULTA_MES_RECLAMADO[True], q)

    def test_descarta_articulos_cuya_premisa_no_se_da(self):
        s = situacion_del_caso(self.informe)
        self.assertTrue(premisa_no_cumplida({"article": "92", "numeral": "92.3", "texto": "92.3. En caso"}, s))
        self.assertIsNone(premisa_no_cumplida({"article": "92", "numeral": "92.1", "texto": "92.1. Se"}, s))
        self.assertTrue(premisa_no_cumplida({"article": "93", "numeral": "93.2", "texto":
            "93.2. Predio con una sola unidad de uso, servido por una conexión de agua potable sin medidor"}, s))
        self.assertTrue(premisa_no_cumplida({"article": "91", "numeral": "91 e)", "texto":
            "e) Brindar información: La empresa prestadora que instale medidores por primera vez"}, s))
        self.assertIsNone(premisa_no_cumplida({"article": "91", "numeral": "91 f)", "texto":
            "f) Diferencia de lecturas válida"}, s))
        self.assertIsNone(premisa_no_cumplida({"article": "92", "numeral": "92.3", "texto": ""}, None))


class TestHistorialConsumos(unittest.TestCase):
    def test_rango_sin_el_mes_reclamado(self):
        registros = [{"anio": 2026, "mes": m, "consumo": c}
                     for m, c in [(6, 52.0), (7, 62.0), (8, 66.0), (9, 99.0)]]
        informe = _informe([BloqueMedio("tarjeta_lectura", "Tarjeta", {"registros": registros}, "",
                                        constataciones=[_hecho("lecturaMesReclamado", periodo="2026-09")])])
        texto = _historial_consumos(informe)
        self.assertIn("entre 52 y 66 m³", texto)


if __name__ == "__main__":
    unittest.main()
