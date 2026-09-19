import json
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.src.application.services.informe.informe_service import (
    rehidratar_informe_desde_sysco,
)
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.investigacion.investigacion_service import (
    analizar_medios_en_paralelo,
)
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion
from app.src.infrastructure.api_rest.reclamos import iniciar_investigacion
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoRequest,
    IniciarInvestigacionRequest,
)


class RouterFalso:
    def __init__(self, respuesta: dict | None = None):
        self.respuesta = respuesta
        self.llamadas = 0

    def generar_json(self, mensajes, modelo_id, esquema=None, temperatura=0.0):
        self.llamadas += 1
        if self.respuesta is None:
            raise AssertionError("El LLM no debía ser invocado")
        return json.dumps(self.respuesta, ensure_ascii=False)


def nuevo_informe() -> InformeAtencion:
    informe = InformeAtencion(
        numero="251819-2026-EMAPA-SM",
        fecha=datetime(2026, 9, 19),
        asunto="RESULTADOS",
        reclamo="251819",
        suministro="2056",
    )
    informe.medios_probatorios = [
        {"id": "tarjeta_lectura", "nombre": "Tarjeta de Lectura"},
    ]
    return informe


def con_inspecciones(detalle: dict) -> dict:
    return {
        "data": {
            **detalle,
            "inspeccion_interna": [{"nroinspeccion": 11102}],
            "inspeccion_externa": [{"nroinspeccion": 11109}],
        }
    }


class RehidratacionSyscoTests(unittest.TestCase):
    def test_pendiente_con_inspecciones_no_invoca_llm(self):
        informe = nuevo_informe()
        router = RouterFalso()

        resumenes = rehidratar_informe_desde_sysco(
            informe,
            con_inspecciones({"datos_atencion": {"considerando": "PENDIENTE"}}),
            router,
        )

        self.assertIsNone(resumenes)
        self.assertEqual(0, router.llamadas)
        self.assertIsNone(informe.conclusion)

    def test_pendiente_sin_inspecciones_devuelve_conflicto(self):
        with self.assertRaises(HTTPException) as contexto:
            rehidratar_informe_desde_sysco(
                nuevo_informe(),
                {"data": {"datos_atencion": {"considerando": "PENDIENTE"}}},
                RouterFalso(),
            )

        self.assertEqual(409, contexto.exception.status_code)
        self.assertIn("interna, externa", contexto.exception.detail)

    def test_formato_generado_se_extrae_sin_llm(self):
        texto = """1. Tarjeta de Lecturas: Las lecturas fueron verificadas.

2. De acuerdo con el artículo 88, la facturación es correcta.

En consecuencia, el consumo corresponde a lecturas reales, por lo tanto se declara INFUNDADO."""
        informe = nuevo_informe()
        router = RouterFalso()

        resumenes = rehidratar_informe_desde_sysco(
            informe,
            con_inspecciones({"datos_atencion": {"considerando": texto}}),
            router,
        )

        self.assertEqual(
            {"tarjeta_lectura": "Las lecturas fueron verificadas."},
            resumenes,
        )
        self.assertEqual(0, router.llamadas)
        self.assertEqual("INFUNDADO", informe.veredicto)
        self.assertEqual(
            "De acuerdo con el artículo 88, la facturación es correcta.",
            informe.fundamentacion_normativa,
        )
        self.assertEqual(texto, construir_texto_informe(informe))

    def test_texto_manual_usa_llm_y_recupera_pasos_posteriores(self):
        conclusion = (
            "POR LO TANTO, SE DECLARA INFUNDADO EL RECLAMO Y SE MANTIENE "
            "EL MONTO FACTURADO."
        )
        texto = (
            "SE VERIFICARON LAS INSTALACIONES Y LAS LECTURAS.\n"
            "DE ACUERDO CON EL REGLAMENTO, EL CONSUMO ES REAL.\n"
            f"{conclusion}\n"
            "EL PROCEDIMIENTO CONTINÚA CONFORME A LEY."
        )
        informe = nuevo_informe()
        router = RouterFalso({
            "fundamentacion": "DE ACUERDO CON EL REGLAMENTO, EL CONSUMO ES REAL.",
            "conclusion": conclusion,
            "veredicto": "INFUNDADO",
        })
        datos = con_inspecciones({
            "datos_atencion": {
                "considerando": texto,
                "propuestaeps": "MANTENER EL MONTO FACTURADO",
            },
            "datos_resolucion": {"resuelve": "SE RESUELVE DECLARAR INFUNDADO"},
        })

        resumenes = rehidratar_informe_desde_sysco(informe, datos, router)

        self.assertEqual({}, resumenes)
        self.assertEqual(1, router.llamadas)
        self.assertEqual("INFUNDADO", informe.veredicto)
        self.assertEqual(conclusion, informe.conclusion)
        self.assertEqual("MANTENER EL MONTO FACTURADO", informe.propuesta_conciliacion.propuesta_empresa)
        self.assertEqual("", informe.propuesta_conciliacion.propuesta_reclamante)
        self.assertEqual("SE RESUELVE DECLARAR INFUNDADO", informe.resolucion)

    def test_ultimo_medio_no_se_confunde_con_fundamentacion(self):
        texto = """INFORME N.º 251819-2026-EMAPA-SM

A         : Jefatura
ASUNTO    : RESULTADOS
REF.      : RECLAMO 251819
FECHA     : 19 de septiembre del 2026

Mediante el presente, me dirijo a Usted, para informarle el resultado:

1. Tarjeta de Lecturas: No se encontraron anomalías.

En consecuencia, la facturación es correcta y se declara INFUNDADO."""
        informe = nuevo_informe()

        resumenes = rehidratar_informe_desde_sysco(
            informe,
            con_inspecciones({"datos_atencion": {"considerando": texto}}),
            RouterFalso(),
        )

        self.assertEqual(
            {"tarjeta_lectura": "No se encontraron anomalías."},
            resumenes,
        )
        self.assertIsNone(informe.fundamentacion_normativa)

    def test_rechaza_veredicto_inventado_por_llm(self):
        texto = "EL CONSUMO FUE VERIFICADO, SIN DECLARACIÓN EXPRESA."
        router = RouterFalso({
            "fundamentacion": None,
            "conclusion": texto,
            "veredicto": "INFUNDADO",
        })

        with self.assertRaises(HTTPException) as contexto:
            rehidratar_informe_desde_sysco(
                nuevo_informe(),
                con_inspecciones({"datos_atencion": {"considerando": texto}}),
                router,
            )

        self.assertEqual(422, contexto.exception.status_code)


class RecalculoMediosTests(unittest.IsolatedAsyncioTestCase):
    async def test_recalcula_datos_sin_generar_otro_resumen(self):
        codreclamo = "test-rehidratacion-medios"
        informe_store.eliminar(codreclamo)
        informe_store.crear_metadata(codreclamo, "2056")

        class AnalistaFalso:
            def __init__(self, *args, **kwargs):
                pass

            def analizar(self, **kwargs):
                raise AssertionError("No debía regenerarse el resumen con LLM")

            def preprocesar(self, *args, **kwargs):
                return {"categoria": "DOMESTICO"}, [], [(2026, 7)]

        request = BuscarReclamoRequest(
            codsuc="001",
            codreclamo=codreclamo,
            codcliente="2056",
            clasificacion="A1. CONSUMO MEDIDO",
        )
        try:
            with (
                patch(
                    "app.src.application.services.investigacion.investigacion_service."
                    "asegurar_token_emapa",
                    new=AsyncMock(),
                ),
                patch(
                    "app.src.application.services.investigacion.investigacion_service."
                    "AnalistaMedioAgent",
                    AnalistaFalso,
                ),
            ):
                analizados, omitidos = await analizar_medios_en_paralelo(
                    request,
                    [("record_facturacion", "Récord de Facturación")],
                    api=object(),
                    llm_router=object(),
                    resumenes_existentes={
                        "record_facturacion": "Resumen conservado del informe."
                    },
                )

            informe = informe_store.obtener(codreclamo)
            self.assertEqual(["record_facturacion"], analizados)
            self.assertEqual([], omitidos)
            self.assertEqual("Resumen conservado del informe.", informe.bloques[0].resumen)
            self.assertEqual({"categoria": "DOMESTICO"}, informe.bloques[0].entidad)
            self.assertEqual([(2026, 7)], informe.ventana_meses)
        finally:
            informe_store.eliminar(codreclamo)


class ReaperturaModalTests(unittest.IsolatedAsyncioTestCase):
    async def test_informe_en_memoria_se_devuelve_sin_rehidratar(self):
        codreclamo = "test-reapertura-modal"
        informe_store.eliminar(codreclamo)
        informe = informe_store.crear_metadata(
            codreclamo,
            "2056",
            sesion_id="modal-1",
        )
        informe.medios_probatorios = [
            {"id": "tarjeta_lectura", "nombre": "Tarjeta de Lectura"},
        ]
        informe.veredicto = "INFUNDADO"
        informe.conclusion = "En consecuencia, se declara INFUNDADO."
        informe.agregar_bloque(BloqueMedio(
            medio_id="tarjeta_lectura",
            medio_nombre="Tarjeta de Lectura",
            entidad={"dato": "conservado"},
            resumen="Resumen conservado en memoria.",
        ))
        request = IniciarInvestigacionRequest(
            codreclamo=codreclamo,
            codcliente="2056",
            sesion_id="modal-1",
            datos={
                "data": {
                    "codreclamo": "001",
                    "codcliente": 2056,
                    "codsuc": "001",
                    "datos_atencion": {"considerando": "PENDIENTE"},
                    "inspeccion_interna": [{"nroinspeccion": 11102}],
                    "inspeccion_externa": [{"nroinspeccion": 11109}],
                }
            },
        )

        try:
            with patch(
                "app.src.infrastructure.api_rest.reclamos."
                "rehidratar_informe_desde_sysco",
            ) as rehidratar:
                response = await iniciar_investigacion(
                    request,
                    token="token-prueba",
                    llm_router=RouterFalso(),
                )

            rehidratar.assert_not_called()
            self.assertEqual("existente", response.estado)
            self.assertEqual("INFUNDADO", response.veredicto)
            tarjeta = next(
                medio
                for medio in response.analisis_medios
                if medio.medio_id == "tarjeta_lectura"
            )
            self.assertEqual("ok", tarjeta.fase)
            self.assertEqual(
                "Resumen conservado en memoria.",
                tarjeta.resumen,
            )
            self.assertEqual(
                {"dato": "conservado"},
                tarjeta.datos,
            )
        finally:
            informe_store.eliminar(codreclamo)


if __name__ == "__main__":
    unittest.main()
