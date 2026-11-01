"""Formato de EMAPA para la propuesta de conciliación y la resolución, y
actualización del informe de atención con el resultado de la audiencia."""

import asyncio
import unittest

from app.src.application.services.informe import formatos
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.services.investigacion.conciliacion_service import (
    actualizar_conciliacion, generar_propuesta_conciliacion,
)
from app.src.application.services.investigacion.resolucion_service import generar_resolucion_final
from app.src.core.model.informe_atencion import ProblemaNormado
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ActualizarConciliacionRequest, ConciliacionRequest, ResolucionRequest,
)
from app.tests.test_evidencias import informe_ejemplo

COD = "900777"
SUSTENTO = "EL CONSUMO FACTURADO SE AJUSTA A REGISTROS REALES CONFORME AL ANÁLISIS TÉCNICO EFECTUADO"


class RouterFalso:
    """Devuelve las respuestas en orden; registra los prompts recibidos."""
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.prompts = []

    def generar_texto(self, mensajes, modelo_id=None, **_):
        self.prompts.append(mensajes[0].contenido)
        return self.respuestas.pop(0)


def preparar(veredicto="INFUNDADO"):
    inf = informe_ejemplo(COD)
    inf.datos_reclamo.reclamante = "Rodriguez Almera Jesus"
    inf.datos_reclamo.dni = "00000000"
    inf.veredicto = veredicto
    inf.conclusion = "En consecuencia, ... se declara " + veredicto
    inf.estado_evaluacion = "completada"
    inf.bloques[0].problemas.append(ProblemaNormado(
        tipo="errorConsumo", detalle="x", seleccionado=True,
        articulos=[{"numeral": "88.4", "aplica": True}, {"numeral": "12", "aplica": False}],
    ))
    informe_store._data[COD] = inf
    return inf


class TestTextos(unittest.TestCase):
    def tearDown(self):
        informe_store._data.pop(COD, None)

    def test_periodos(self):
        self.assertEqual(formatos.periodos_texto("SETIEMBRE-2026"), "AL MES SETIEMBRE 2026")
        self.assertEqual(formatos.periodos_texto("JULIO-2026, AGOSTO-2026"),
                         "A LOS MESES JULIO 2026 Y AGOSTO 2026")
        self.assertEqual(formatos.periodos_texto(None), "AL MES RECLAMADO")

    def test_articulos_solo_aplicables(self):
        self.assertEqual(formatos.articulos_citados(preparar()), ["88.4"])

    def test_propuesta_segun_resultado(self):
        inf = preparar()
        c = inf.propuesta_conciliacion = formatos.Conciliacion()
        pendiente = formatos.propuesta_conciliacion(inf, SUSTENTO, c)
        self.assertIn("LA EPS PROPONE", pendiente)
        self.assertNotIn("ACEPTA", pendiente)
        c.asistio, c.subsiste = True, False
        acepta = formatos.propuesta_conciliacion(inf, SUSTENTO, c)
        self.assertTrue(acepta.startswith("EN PRESENCIA DEL RECLAMANTE SR(A). RODRIGUEZ ALMERA JESUS, CON DNI N° 00000000"))
        self.assertIn("058-2023-SUNASS-CD", acepta)
        self.assertIn("DECLARAR INFUNDADO EL PRESENTE RECLAMO CORRESPONDIENTE AL MES SETIEMBRE 2026.", acepta)
        self.assertIn(f"AL HABERSE VERIFICADO QUE {SUSTENTO}; ADEMÁS, SE ENCUENTRA ACORDE A LO DESCRITO "
                      "EN LA NORMATIVA, SEÑALADA EN EL ART. 88.4,", acepta)
        self.assertTrue(acepta.endswith("EL USUARIO ACEPTA LA PROPUESTA DE CONCILIACIÓN PLANTEADA POR LA EPS "
                                        "RESPECTO A DECLARAR INFUNDADO EL PRESENTE RECLAMO. EL PROCEDIMIENTO "
                                        "CONTINÚA CONFORME A LEY."))
        c.subsiste = True
        self.assertIn("NO ACEPTA", formatos.propuesta_conciliacion(inf, SUSTENTO, c))
        c.asistio = False
        self.assertTrue(formatos.propuesta_conciliacion(inf, SUSTENTO, c).startswith("ANTE LA INASISTENCIA"))

    def test_se_resuelve(self):
        inf = preparar()
        texto = formatos.se_resuelve(inf)
        self.assertIn("015-2023-SUNASS-CD", texto)
        self.assertIn("SE DECLARA INFUNDADO EL PRESENTE RECLAMO.", texto)
        self.assertNotIn("REFACTURACIÓN", texto)
        self.assertIn("JIRÓN MANUELA MOREY N°110 - TARAPOTO", texto)
        inf.veredicto = "FUNDADO"
        texto = formatos.se_resuelve(inf, ["SE REFACTURA SETIEMBRE 2026 POR 39 M3 [S/ IMPORTE]"])
        self.assertIn("PROCEDIMIENTO DE REFACTURACIÓN:\n1. SE REFACTURA SETIEMBRE 2026 POR 39 M3 [S/ IMPORTE].", texto)
        self.assertIn("SETIEMBRE-2026 | 885 | 934 | 49", texto)


class TestFlujo(unittest.TestCase):
    def tearDown(self):
        informe_store._data.pop(COD, None)

    def test_conciliacion_resultado_e_informe(self):
        inf = preparar()
        router = RouterFalso(SUSTENTO)
        r = asyncio.run(generar_propuesta_conciliacion(ConciliacionRequest(codreclamo=COD), router))
        self.assertIn("LA EPS PROPONE", r.propuesta)
        self.assertNotIn("Resultado de la conciliación", construir_texto_informe(inf))

        resp = actualizar_conciliacion(ActualizarConciliacionRequest(
            codreclamo=COD, asistio=True, subsiste=False, fecha_audiencia="26/10/2026"))
        self.assertEqual(resp.resultado, "acepta")
        self.assertTrue(resp.propuesta_regenerada)
        self.assertTrue(resp.propuesta_empresa.startswith("EN PRESENCIA DEL RECLAMANTE"))
        self.assertEqual(resp.propuesta_reclamante, "ACEPTAR LA PROPUESTA DE LA EPS")
        self.assertIn("Resultado de la conciliación: realizada la audiencia de conciliación el 26/10/2026, "
                      "el usuario aceptó", construir_texto_informe(inf))

        # Un texto editado a mano no se reescribe solo…
        informe_store.actualizar_propuesta(COD, "TEXTO PROPIO")
        resp = actualizar_conciliacion(ActualizarConciliacionRequest(codreclamo=COD, subsiste=True))
        self.assertEqual(resp.resultado, "no_acepta")
        self.assertFalse(resp.propuesta_regenerada)
        self.assertEqual(resp.propuesta_empresa, "TEXTO PROPIO")
        self.assertEqual(resp.puntos_desacuerdo, "LO PROPUESTO POR LA EPS")
        # …salvo que se pida reaplicar el formato.
        resp = actualizar_conciliacion(ActualizarConciliacionRequest(codreclamo=COD, reaplicar_formato=True))
        self.assertIn("NO ACEPTA", resp.propuesta_empresa)

        resp = actualizar_conciliacion(ActualizarConciliacionRequest(codreclamo=COD, asistio=False))
        self.assertEqual(resp.resultado, "no_asistio")
        self.assertIn("el usuario no asistió", construir_texto_informe(inf))

    def test_resolucion_fundado(self):
        inf = preparar("FUNDADO")
        actualizar_conciliacion(ActualizarConciliacionRequest(codreclamo=COD, asistio=True, subsiste=True))
        inf.propuesta_conciliacion.propuesta_empresa = "PROPUESTA"
        router = RouterFalso("QUE, SEGÚN INFORME ... SE DECLARA FUNDADO.",
                             '["SE REFACTURARÁ SETIEMBRE 2026 POR EL PROMEDIO DE 39 M3 [S/ IMPORTE]"]')
        r = asyncio.run(generar_resolucion_final(ResolucionRequest(codreclamo=COD), router))
        self.assertIn("NO ACEPTÓ", router.prompts[0])           # el resultado llega al redactor
        self.assertIn("SE DECLARA FUNDADO EL PRESENTE RECLAMO.", r.se_resuelve)
        self.assertIn("1. SE REFACTURARÁ SETIEMBRE 2026 POR EL PROMEDIO DE 39 M3 [S/ IMPORTE].", r.se_resuelve)
        self.assertIn("MES | LECT. ANTERIOR | LECT. ÚLTIMA | CONS. FACTURAR M3", r.se_resuelve)
        self.assertEqual(inf.se_resuelve, r.se_resuelve)


if __name__ == "__main__":
    unittest.main()
