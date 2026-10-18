import unittest
from dataclasses import asdict

import pandas as pd

from app.src.application.services.pre_proces.pre_targeta_lecturas_service import (
    PreTargetaLecturasService,
)
from app.src.application.services.pre_proces.problemas_normalizer import (
    _fugas_desde_observaciones,
    problemas_de_inspeccion_externa,
    problemas_de_targeta,
)
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.application.usecase.agents.fundamentacion_normativa import CONSULTA_POR_TIPO
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion
from app.src.core.model.inspeccion_externa import InspeccionExterna
from app.src.core.model.targeta_lecturas import TargetaLecturas


class ObservacionesFugaTests(unittest.TestCase):
    def test_clasifica_modalidad_sin_perder_oracion_fuente_u_original(self):
        casos = [
            ("Se detectó fuga visible en inodoro", "fugaVisible"),
            ("Se detectó fuga no visible", "fugaNoVisible"),
            ("No se detectó fuga visible", "fugaNoDetectada"),
            ("Se descarta fuga no visible", "fugaNoDetectada"),
            ("Se sospecha una fuga no visible", "fugaSospechada"),
            ("El usuario refiere una fuga", "fugaReferida"),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                problemas = _fugas_desde_observaciones([("observaciones", texto)])
                self.assertEqual([esperado], [p.tipo for p in problemas])
                self.assertEqual(texto, problemas[0].detalle)
                self.assertEqual(texto, problemas[0].texto_original)
                self.assertEqual("observaciones", problemas[0].fuente)

    def test_procesa_negacion_y_hallazgo_en_oraciones_distintas(self):
        texto = "No hay fuga en el inodoro. Se detectó fuga en la tubería"
        problemas = _fugas_desde_observaciones([("obsinsinteriores", texto)])
        self.assertEqual(["fugaNoDetectada", "fugas"], [p.tipo for p in problemas])
        self.assertEqual("No hay fuga en el inodoro.", problemas[0].detalle)
        self.assertEqual("Se detectó fuga en la tubería", problemas[1].detalle)
        self.assertTrue(all(p.texto_original == texto for p in problemas))

    def test_procesa_menciones_opuestas_en_una_misma_oracion(self):
        texto = "No hay fuga en el inodoro y se detectó fuga en la tubería"
        problemas = _fugas_desde_observaciones([texto])
        self.assertEqual(["fugaNoDetectada", "fugas"], [p.tipo for p in problemas])

    def test_contradiccion_estructurada_no_se_resuelve_silenciosamente(self):
        inspeccion = InspeccionExterna(
            fugas="Se detectaron fugas de agua.",
            observacionmed="No se detectó fuga visible",
        )
        problemas = problemas_de_inspeccion_externa(inspeccion)
        self.assertIn("fugas", [p.tipo for p in problemas])
        self.assertIn("fugaNoDetectada", [p.tipo for p in problemas])
        self.assertIn("contradiccionFuga", [p.tipo for p in problemas])

    def test_texto_vacio_o_sin_fuga_no_genera_hallazgos(self):
        self.assertEqual([], _fugas_desde_observaciones([None, "", "Medidor operativo"]))

    def test_no_visible_no_es_negacion(self):
        problema = _fugas_desde_observaciones(["Se detectó fuga no visible"])[0]
        self.assertEqual("fugaNoVisible", problema.tipo)


class DescensoConsumoTests(unittest.TestCase):
    def setUp(self):
        self.servicio = object.__new__(PreTargetaLecturasService)

    @staticmethod
    def _df(consumos, promedios=None):
        promedios = promedios or [20] * len(consumos)
        return pd.DataFrame([
            {
                "anio": 2026,
                "mes": indice + 1,
                "consumo": consumo,
                "lecturapromedio": promedio,
                "estadolectura": "000",
            }
            for indice, (consumo, promedio) in enumerate(zip(consumos, promedios))
        ])

    def test_describe_descenso_con_periodos_consumos_y_promedios(self):
        hallazgos = self.servicio._detectar_descenso_consumo(self._df([60, 20]))
        self.assertEqual(1, len(hallazgos))
        texto = hallazgos[0]
        for valor in ("60 m³", "01/2026", "20 m³", "02/2026", "promedio 20 m³"):
            self.assertIn(valor, texto)
        for afirmacion_no_acreditada in ("fuga", "repar", "visible"):
            self.assertNotIn(afirmacion_no_acreditada, texto.lower())

    def test_consumo_posterior_cero_no_afirma_reparacion(self):
        texto = self.servicio._detectar_descenso_consumo(self._df([60, 0]))[0]
        self.assertIn("0 m³", texto)
        self.assertNotIn("repar", texto.lower())

    def test_sin_descenso_no_genera_patron(self):
        self.assertEqual([], self.servicio._detectar_descenso_consumo(self._df([60, 40])))

    def test_datos_insuficientes_o_faltantes_no_inventan_resultado(self):
        self.assertEqual([], self.servicio._detectar_descenso_consumo(self._df([60])))
        self.assertEqual(
            [],
            self.servicio._detectar_descenso_consumo(self._df([60, None], [20, 20])),
        )

    def test_tipo_normalizado_y_consulta_rag_son_neutrales(self):
        targeta = TargetaLecturas(descensoConsumo=["Descenso cuantitativo de prueba."])
        problema = problemas_de_targeta(targeta)[0]
        self.assertEqual("descensoConsumo", problema.tipo)
        consulta = CONSULTA_POR_TIPO[problema.tipo].lower()
        self.assertNotIn("repar", consulta)
        self.assertNotIn("no visible", consulta)

    def test_hallazgo_llega_al_contexto_de_conclusion_sin_cambiar_decision(self):
        targeta = TargetaLecturas(descensoConsumo=["Descenso cuantitativo de prueba."])
        bloque = BloqueMedio(
            medio_id="tarjeta_lectura",
            medio_nombre="Tarjeta de lectura",
            entidad=asdict(targeta),
            resumen="Serie mensual revisada.",
            problemas=problemas_de_targeta(targeta),
        )
        informe = InformeAtencion(
            numero="1", fecha=pd.Timestamp("2026-01-01").to_pydatetime(),
            asunto="prueba", reclamo="1", suministro="1", bloques=[bloque],
        )
        contexto = ConclusionAgent._hallazgos_por_medio(informe)["tarjeta_lectura"]
        self.assertIn("Descenso cuantitativo de prueba.", contexto)
        self.assertNotIn("fuga", contexto.lower())


if __name__ == "__main__":
    unittest.main()
