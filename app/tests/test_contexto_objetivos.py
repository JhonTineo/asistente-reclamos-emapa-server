import json
import unittest
from datetime import datetime

from app.src.application.services.investigacion.investigacion_service import (
    enfoque_para_medio, medios_determinantes,
)
from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.core.model.informe_atencion import (
    BloqueMedio, InformeAtencion, ObjetivoInvestigacion, ProblemaNormado,
)


class RouterCaptura:
    def generar_texto(self, mensajes, **kwargs):
        self.mensajes = mensajes
        return "Septiembre de 2026 fue facturado por lectura."

    def generar_json(self, mensajes, **kwargs):
        self.mensajes = mensajes
        return json.dumps([{"id": 1, "resultado": "no_evaluable", "evidencia": "sin acceso"}])


class ContextoObjetivosTests(unittest.TestCase):
    def test_facturacion_conserva_septiembre_y_analiza_aun_sin_problemas(self):
        router = RouterCaptura()
        agente = AnalistaMedioAgent(emapa_api=None, llm_router=router)
        datos = {
            "categoria": "COMERCIAL", "formaPredominante": "MEDIDO",
            "mesesPromediados": ["julio de 2026"],
            "rachaPromediados": ["julio por promedio y agosto por lectura"],
            "registros": [{"anio": 2026, "mes": 9, "tipopromedio_texto": "MEDIDO"}],
        }
        for problemas in ([], [ProblemaNormado(tipo="mesesPromediados", detalle="julio")]):
            with self.subTest(problemas=bool(problemas)):
                resumen = agente.interpretar(
                    "record_facturacion", "Facturación", datos, problemas, "A1",
                    "¿Septiembre de 2026 se facturó por lectura o promedio?",
                )
                self.assertIn("Septiembre", resumen)
                system = router.mensajes[0].contenido
                self.assertIn('"registros"', system)
                self.assertIn('"mes": 9', system)
                self.assertIn('"tipopromedio_texto": "MEDIDO"', system)
                self.assertEqual(1, len(datos["registros"]))

    def test_ambas_inspecciones_en_analisis_fundamentacion_y_evaluacion(self):
        for principal in ("inspeccion_interna", "inspeccion_externa"):
            with self.subTest(principal=principal):
                obj = ObjetivoInvestigacion(1, "¿Hay fugas o problemas del medidor?", principal, True)
                problema = ProblemaNormado(tipo="observacion", detalle="medidor nublado")
                informe = InformeAtencion(
                    numero="1", fecha=datetime(2026, 10, 30), asunto="prueba",
                    reclamo="test", suministro="test", objetivos=[obj],
                    bloques=[
                        BloqueMedio("inspeccion_interna", "Interna", {}, "Sin acceso al interior"),
                        BloqueMedio("inspeccion_externa", "Externa", {}, "Medidor nublado", [problema]),
                        BloqueMedio("saldo_detalle", "Saldo", {}, "DATO AJENO"),
                    ],
                )
                for medio in ("inspeccion_interna", "inspeccion_externa"):
                    self.assertEqual(obj.descripcion, enfoque_para_medio(informe, medio))
                self.assertIsNone(enfoque_para_medio(informe, "saldo_detalle"))
                self.assertEqual({"inspeccion_interna", "inspeccion_externa"}, medios_determinantes(informe))
                self.assertEqual([problema], FundamentacionNormativaAgent.pool_determinante(informe))
                router = RouterCaptura()
                agente = ConclusionAgent(router)
                agente._evaluar_objetivos(informe, agente._hallazgos_por_medio(informe))
                human = router.mensajes[1].contenido
                self.assertIn("Sin acceso al interior", human)
                self.assertIn("Medidor nublado", human)
                self.assertNotIn("DATO AJENO", human)

    def test_facturacion_no_recibe_hallazgos_ajenos(self):
        informe = InformeAtencion(
            numero="1", fecha=datetime(2026, 10, 30), asunto="prueba",
            reclamo="test", suministro="test",
            objetivos=[ObjetivoInvestigacion(1, "¿Cómo se facturó septiembre?", "record_facturacion", True)],
        )
        router = RouterCaptura()
        ConclusionAgent(router)._evaluar_objetivos(informe, {
            "record_facturacion": "Septiembre por lectura",
            "inspeccion_externa": "DATO AJENO",
        })
        self.assertIn("Septiembre por lectura", router.mensajes[1].contenido)
        self.assertNotIn("DATO AJENO", router.mensajes[1].contenido)


if __name__ == "__main__":
    unittest.main()
