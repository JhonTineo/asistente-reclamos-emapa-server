import json
import logging
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.registry import ToolRegistry
from app.core.config import settings
from app.core.http import http_get_json

logger = logging.getLogger("tools.emapa_api")


EMAPA_ENDPOINTS = {
    "saldo_actual": {
        "path": "/api-caja/cobranza/obtener-saldo-detalle-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "tarjeta_lectura": {
        "path": "/api-micromedicion/customer-reading/get-customer-card/info/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "record_facturacion": {
        "path": "/api-consulta/facturacion/obtener-record-facturacion-x-cliente-anio/{codsuc}/{codcliente}/{anio}",
        "method": "GET",
    },
    "corte_reapertura": {
        "path": "/api-consulta/catastro/obtener-corte-reapertura-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "inspeccion_externa": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-externa/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "inspeccion_interna": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-interna/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "buscar_reclamo": {
        "path": "/api-reclamos/reclamo/obtener/detalle/{codsede}/{codsuc}/{codreclamo}/{codcliente}",
        "method": "GET",
    },
}


def _get_url(path: str) -> str:
    return f"{settings.emapa_api_base_url}{path}"


def _get_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.emapa_access_token:
        headers["Authorization"] = f"Bearer {settings.emapa_access_token}"
    return headers


def _request(path: str) -> dict[str, Any]:
    url = _get_url(path)
    return http_get_json(
        url=url,
        headers=_get_headers(),
        timeout=float(settings.timeout_seconds),
        retries=int(settings.max_retries),
    )


def buscar_reclamo_emapa(codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["buscar_reclamo"]["path"].format(
        codsede=codsede,
        codsuc=codsuc,
        codreclamo=codreclamo,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_saldo_actual(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["saldo_actual"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_tarjeta_lectura(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["tarjeta_lectura"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_record_facturacion(codsuc: str, codcliente: str, anio: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["record_facturacion"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
        anio=anio,
    )
    return _request(endpoint)


def obtener_corte_reapertura(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["corte_reapertura"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_inspeccion_externa(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["inspeccion_externa"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_inspeccion_interna(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["inspeccion_interna"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


class ConsultarHistoricoReclamosTool(Tool):
    name = "consultar_historico_reclamos"
    description = "Obtiene el histórico de reclamos de un suministro."

    def execute(self, codsede: str, codsuc: str, codreclamo: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = buscar_reclamo_emapa(codsede, codsuc, codreclamo, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarLecturasTool(Tool):
    name = "consultar_lecturas"
    description = "Obtiene el histórico de lecturas de un suministro para el último año."

    def execute(self, codsuc: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = obtener_tarjeta_lectura(codsuc, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarFacturacionesTool(Tool):
    name = "consultar_facturaciones"
    description = "Obtiene el histórico de facturaciones de un suministro para los últimos 1 años."

    def execute(self, codsuc: str, codcliente: str, anio: str, **kwargs) -> ToolResult:
        try:
            response = obtener_record_facturacion(codsuc, codcliente, anio)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarPagosTool(Tool):
    name = "consultar_pagos"
    description = "Obtiene el histórico de pagos de un suministro para el último año."

    def execute(self, codsuc: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = obtener_saldo_actual(codsuc, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarMovimientosTool(Tool):
    name = "consultar_movimientos"
    description = "Obtiene el histórico de cierres y reaperturas de un suministro."

    def execute(self, codsuc: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = obtener_corte_reapertura(codsuc, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInspeccionExtTool(Tool):
    name = "consultar_inspeccion_externa"
    description = "Obtiene el informe de inspección externa de un suministro."

    def execute(self, codsuc: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = obtener_inspeccion_externa(codsuc, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
        except Exception as e:
            logger.error("[TOOL] %s | error=%s", self.name, str(e))
            return ToolResult(success=False, error=str(e))


class ConsultarInspeccionIntTool(Tool):
    name = "consultar_inspeccion_interna"
    description = "Obtiene el informe de inspección interna de un suministro."

    def execute(self, codsuc: str, codcliente: str, **kwargs) -> ToolResult:
        try:
            response = obtener_inspeccion_interna(codsuc, codcliente)
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
            return ToolResult(success=True, data=json.dumps(response, indent=1, ensure_ascii=False))
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
