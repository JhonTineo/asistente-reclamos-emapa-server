import asyncio
import json
import unittest
from datetime import datetime

from fastapi import HTTPException

from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.investigacion.conciliacion_service import (
    generar_propuesta_conciliacion,
)
from app.src.application.services.investigacion.resolucion_service import (
    generar_resolucion_final,
)
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.core.model.informe_atencion import InformeAtencion, ObjetivoInvestigacion
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ConciliacionRequest,
    ResolucionRequest,
)


class RouterFalso:
    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta
        self.error = error
        self.redacciones = 0
        self.mensajes_evaluacion = []
        self.mensajes_redaccion = []

    def generar_json(self, **_kwargs):
        self.mensajes_evaluacion = _kwargs["mensajes"]
        if self.error:
            raise self.error
        if isinstance(self.respuesta, str):
            return self.respuesta
        return json.dumps(self.respuesta, ensure_ascii=False)

    def generar_texto(self, **_kwargs):
        self.redacciones += 1
        self.mensajes_redaccion = _kwargs["mensajes"]
        return "En consecuencia, texto definitivo de prueba."


def informe_con_objetivos(*objetivos):
    return InformeAtencion(
        numero="1", fecha=datetime(2026, 1, 1), asunto="prueba",
        reclamo="r", suministro="s", objetivos=list(objetivos),
    )


def objetivo(oid, determinante=True):
    return ObjetivoInvestigacion(
        id=oid, descripcion=f"Objetivo {oid}", determinante=determinante,
    )


class ConclusionSuficienciaTests(unittest.TestCase):
    def evaluar(self, respuesta, *objetivos):
        router = RouterFalso(respuesta)
        informe = informe_con_objetivos(*objetivos)
        veredicto = ConclusionAgent(router).concluir_y_asignar(informe)
        return informe, router, veredicto

    def test_procede_con_sustento_es_fundado(self):
        informe, router, veredicto = self.evaluar(
            [{"id": 1, "resultado": "procede_correccion", "evidencia": "error medido"}],
            objetivo(1),
        )
        self.assertEqual("FUNDADO", veredicto)
        self.assertEqual("completada", informe.estado_evaluacion)
        self.assertEqual(1, router.redacciones)

    def test_todos_sin_correccion_con_sustento_es_infundado(self):
        informe, _, veredicto = self.evaluar([
            {"id": 1, "resultado": "sin_correccion", "evidencia": "lectura correcta"},
            {"id": 2, "resultado": "sin_correccion", "evidencia": "medidor operativo"},
        ], objetivo(1), objetivo(2))
        self.assertEqual("INFUNDADO", veredicto)
        self.assertEqual("completada", informe.estado_evaluacion)

    def test_no_evaluable_puro_o_mixto_siempre_emite_veredicto(self):
        combinaciones = [
            [{"id": 1, "resultado": "no_evaluable", "evidencia": "falta inspección"}],
            [
                {"id": 1, "resultado": "no_evaluable", "evidencia": ""},
                {"id": 2, "resultado": "no_evaluable", "evidencia": "falta inspección"},
            ],
            [
                {"id": 1, "resultado": "sin_correccion", "evidencia": "lectura correcta"},
                {"id": 2, "resultado": "no_evaluable", "evidencia": "falta inspección"},
            ],
            [
                {"id": 1, "resultado": "procede_correccion", "evidencia": "error medido"},
                {"id": 2, "resultado": "no_evaluable", "evidencia": "falta inspección"},
            ],
        ]
        for respuesta in combinaciones:
            with self.subTest(respuesta=respuesta):
                ids = [objetivo(item["id"]) for item in respuesta]
                informe, router, veredicto = self.evaluar(respuesta, *ids)
                esperado = "FUNDADO" if any(
                    r["resultado"] == "procede_correccion" for r in respuesta
                ) else "INFUNDADO"
                self.assertEqual(esperado, veredicto)
                self.assertEqual(esperado, informe.veredicto)
                self.assertTrue(informe.conclusion)
                self.assertEqual("completada", informe.estado_evaluacion)
                self.assertEqual([], informe.motivos_evaluacion)
                self.assertEqual(1, router.redacciones)
                for obj, entrada in zip(informe.objetivos, respuesta):
                    self.assertEqual(entrada["resultado"], obj.resultado)
                    self.assertEqual(entrada["evidencia"] or None, obj.evidencia)
                if esperado == "INFUNDADO":
                    self.assertIn("No afirmes que toda la facturación es correcta",
                                  router.mensajes_redaccion[0].contenido)

    def test_no_evaluable_con_redaccion_fallida_tiene_conclusion_de_respaldo(self):
        class RouterSinRedaccion(RouterFalso):
            def generar_texto(self, **kwargs):
                raise RuntimeError("redacción no disponible")

        router = RouterSinRedaccion([
            {"id": 1, "resultado": "no_evaluable", "evidencia": "sin acceso"},
        ])
        informe = informe_con_objetivos(objetivo(1))
        self.assertEqual("INFUNDADO", ConclusionAgent(router).concluir_y_asignar(informe))
        self.assertEqual("completada", informe.estado_evaluacion)
        self.assertIn("no se acreditó", informe.conclusion)
        self.assertNotIn("no corresponde corregir", informe.conclusion)

    def test_sin_determinantes_requiere_revision(self):
        informe, router, veredicto = self.evaluar([], objetivo(1, False))
        self.assertIsNone(veredicto)
        self.assertEqual("requiere_revision", informe.estado_evaluacion)
        self.assertEqual("SIN_OBJETIVOS_DETERMINANTES", informe.motivos_evaluacion[0].codigo)
        self.assertEqual(0, router.redacciones)

    def test_sin_objetivos_requiere_revision(self):
        informe, router, veredicto = self.evaluar([])
        self.assertIsNone(veredicto)
        self.assertEqual("SIN_OBJETIVOS", informe.motivos_evaluacion[0].codigo)
        self.assertEqual(0, router.redacciones)

    def test_respuestas_invalidas_son_error_sin_redaccion(self):
        casos = [
            ("", "RESPUESTA_VACIA"),
            ("no-json", "JSON_INVALIDO"),
            ([], "OBJETIVOS_OMITIDOS"),
            ([{"id": 1, "resultado": "sin_correccion", "evidencia": "ok"},
              {"id": 1, "resultado": "sin_correccion", "evidencia": "ok"}], "IDENTIFICADOR_DUPLICADO"),
            ([{"id": 9, "resultado": "sin_correccion", "evidencia": "ok"}], "IDENTIFICADOR_DESCONOCIDO"),
            ([{"id": 1, "resultado": "otro", "evidencia": "ok"}], "RESULTADO_INVALIDO"),
            ([{"id": 1, "resultado": "sin_correccion", "evidencia": ""}], "EVIDENCIA_OBLIGATORIA"),
        ]
        for respuesta, codigo in casos:
            with self.subTest(codigo=codigo):
                informe, router, veredicto = self.evaluar(respuesta, objetivo(1))
                self.assertIsNone(veredicto)
                self.assertEqual("error_evaluacion", informe.estado_evaluacion)
                self.assertEqual(codigo, informe.motivos_evaluacion[0].codigo)
                self.assertEqual(0, router.redacciones)

    def test_error_proveedor_es_explicito(self):
        router = RouterFalso(error=RuntimeError("sin conexión"))
        informe = informe_con_objetivos(objetivo(1))
        self.assertIsNone(ConclusionAgent(router).concluir_y_asignar(informe))
        self.assertEqual("ERROR_PROVEEDOR", informe.motivos_evaluacion[0].codigo)
        self.assertIsNone(informe.veredicto)

    def test_regeneracion_fallida_archiva_y_no_reutiliza_decision(self):
        informe = informe_con_objetivos(objetivo(1))
        informe.veredicto = "FUNDADO"
        informe.conclusion = "Conclusión anterior"
        informe.estado_evaluacion = "completada"
        router = RouterFalso("")
        ConclusionAgent(router).concluir_y_asignar(informe)
        self.assertIsNone(informe.veredicto)
        self.assertIsNone(informe.conclusion)
        self.assertEqual("FUNDADO", informe.historial_decisiones[-1]["veredicto"])

    def test_documentos_definitivos_bloqueados_sin_decision(self):
        codigo = "test-sin-decision"
        informe = informe_store.crear_metadata(codigo, "s")
        informe.estado_evaluacion = "requiere_evidencia"
        try:
            with self.assertRaises(HTTPException) as conc:
                asyncio.run(generar_propuesta_conciliacion(
                    ConciliacionRequest(codreclamo=codigo), RouterFalso([]),
                ))
            self.assertEqual(409, conc.exception.status_code)
            with self.assertRaises(HTTPException) as res:
                asyncio.run(generar_resolucion_final(
                    ResolucionRequest(codreclamo=codigo), RouterFalso([]),
                ))
            self.assertEqual(409, res.exception.status_code)
        finally:
            informe_store.eliminar(codigo)


if __name__ == "__main__":
    unittest.main()
