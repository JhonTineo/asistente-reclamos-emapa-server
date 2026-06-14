import json
import logging
from app.tools.base import Tool, ToolResult
from app.tools.registry import ToolRegistry
from app.core.config import settings

logger = logging.getLogger("tools.emapa_api")


def _get_url(path: str) -> str:
    return f"{settings.emapa_api_base_url}{path}"


class ConsultarHistoricoReclamosTool(Tool):
    name = "consultar_historico_reclamos"
    description = "Obtiene el histórico de reclamos de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/reclamos")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarLecturasTool(Tool):
    name = "consultar_lecturas"
    description = "Obtiene el histórico de lecturas de un suministro para los últimos 2 años."

    def execute(self, suministro_id: str, periodo: str = "2y", **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/lecturas")
            response = _mock_request(url, params={"periodo": periodo, "suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarFacturacionesTool(Tool):
    name = "consultar_facturaciones"
    description = "Obtiene el histórico de facturaciones de un suministro para los últimos 2 años."

    def execute(self, suministro_id: str, periodo: str = "2y", **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/facturaciones")
            response = _mock_request(url, params={"periodo": periodo, "suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarPagosTool(Tool):
    name = "consultar_pagos"
    description = "Obtiene el histórico de pagos de un suministro para los últimos 2 años."

    def execute(self, suministro_id: str, periodo: str = "2y", **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/pagos")
            response = _mock_request(url, params={"periodo": periodo, "suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarMovimientosTool(Tool):
    name = "consultar_movimientos"
    description = "Obtiene el histórico de cierres y reaperturas de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/movimientos")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInspeccionExtTool(Tool):
    name = "consultar_inspeccion_externa"
    description = "Obtiene el informe de inspección externa de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/inspecciones/externa")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInspeccionIntTool(Tool):
    name = "consultar_inspeccion_interna"
    description = "Obtiene el informe de inspección interna de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/inspecciones/interna")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarRecibosTool(Tool):
    name = "consultar_recibos"
    description = "Obtiene copia de los recibos de pago de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/recibos")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInformeRegimenTool(Tool):
    name = "consultar_informe_regimen"
    description = "Obtiene el informe de aplicación del régimen de facturación."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/informes/regimen")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInformePromedioTool(Tool):
    name = "consultar_informe_promedio"
    description = "Obtiene el informe de cálculo y aplicación del promedio de facturación."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/informes/promedio")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInformeAsignacionTool(Tool):
    name = "consultar_informe_asignacion"
    description = "Obtiene el informe de asignación de consumo aplicado."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/informes/asignacion")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarOrdenServicioTool(Tool):
    name = "consultar_orden_servicio"
    description = "Obtiene la orden de servicio de verificación de uso indebido."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/ordenes/servicio")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarLiquidacionTool(Tool):
    name = "consultar_liquidacion"
    description = "Obtiene la liquidación comercial de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/liquidaciones")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarMesesAdeudadosTool(Tool):
    name = "consultar_meses_adeudados"
    description = "Obtiene los meses adeudados de un suministro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/deuda/meses")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarConceptosFacturadosTool(Tool):
    name = "consultar_conceptos_facturados"
    description = "Obtiene los conceptos facturados después del cierre."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/conceptos/facturados")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarResponsabilidadTool(Tool):
    name = "consultar_responsabilidad"
    description = "Obtiene documento de responsabilidad de otra persona."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/documentos/responsabilidad")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarAccionesCobranzaTool(Tool):
    name = "consultar_acciones_cobranza"
    description = "Obtiene las acciones adoptadas por la empresa para el pago."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/cobranza/acciones")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarUnidadesUsoTool(Tool):
    name = "consultar_unidades_uso"
    description = "Obtiene el tipo y número de unidades de uso facturadas."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/unidades/uso")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarCroquisTool(Tool):
    name = "consultar_croquis"
    description = "Obtiene el croquis del predio con puntos de agua y desagüe."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/croquis")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarAvisosCobranzaTool(Tool):
    name = "consultar_avisos_cobranza"
    description = "Obtiene los avisos de cobranza con montos."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/avisos/cobranza")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarDocumentacionCobroTool(Tool):
    name = "consultar_documentacion_cobro"
    description = "Obtiene la documentación que sustenta el cobro."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/documentos/cobro")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInformeTecnicoTool(Tool):
    name = "consultar_informe_tecnico"
    description = "Obtiene el informe del área técnica de la empresa."

    def execute(self, suministro_id: str, **kwargs) -> ToolResult:
        try:
            url = _get_url(f"/suministros/{suministro_id}/informes/tecnico")
            response = _mock_request(url, params={"suministro_id": suministro_id})
            return ToolResult(success=True, data=json.dumps(response, indent=2))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


def _mock_request(url: str, params: dict) -> dict:
    suministro_id = params.get("suministro_id", "unknown")
    logger.info("[MOCK] Request to %s for suministro %s", url, suministro_id)
    return {
        "suministro_id": suministro_id,
        "url": url,
        "status": "mock_data",
        "message": f"Datos simulados para {url}. API real no configurada.",
        "params": params,
    }


def register_all_tools() -> None:
    tools = [
        ConsultarHistoricoReclamosTool(),
        ConsultarLecturasTool(),
        ConsultarFacturacionesTool(),
        ConsultarPagosTool(),
        ConsultarMovimientosTool(),
        ConsultarInspeccionExtTool(),
        ConsultarInspeccionIntTool(),
        ConsultarRecibosTool(),
        ConsultarInformeRegimenTool(),
        ConsultarInformePromedioTool(),
        ConsultarInformeAsignacionTool(),
        ConsultarOrdenServicioTool(),
        ConsultarLiquidacionTool(),
        ConsultarMesesAdeudadosTool(),
        ConsultarConceptosFacturadosTool(),
        ConsultarResponsabilidadTool(),
        ConsultarAccionesCobranzaTool(),
        ConsultarUnidadesUsoTool(),
        ConsultarCroquisTool(),
        ConsultarAvisosCobranzaTool(),
        ConsultarDocumentacionCobroTool(),
        ConsultarInformeTecnicoTool(),
    ]
    for tool in tools:
        ToolRegistry.register(tool, roles=["investigador"])
    logger.info("[TOOLS] Registered %d EMAPA API tools", len(tools))


register_all_tools()
