MEDIO_TO_TOOL: dict[str, str] = {
    "Histórico de reclamos del suministro.": "consultar_historico_reclamos",
    "Histórico de Lecturas periodo de dos (2) años.": "consultar_lecturas",
    "Histórico de Facturaciones periodo de dos (2) años.": "consultar_facturaciones",
    "Histórico de Pagos periodo de dos (2) años.": "consultar_pagos",
    "Históricos de cierres y reaperturas.": "consultar_movimientos",
    "Inspección externa.": "consultar_inspeccion_externa",
    "Inspección interna.": "consultar_inspeccion_interna",
    "Copia de los recibos de pago reclamados.": "consultar_recibos",
    "Copia simple del recibo de pago cancelado.": "consultar_recibos",
    "Copia simple del nuevo recibo.": "consultar_recibos",
    "Informe de aplicación del régimen de facturación.": "consultar_informe_regimen",
    "Informe de cálculo y aplicación del promedio de facturación.": "consultar_informe_promedio",
    "Informe de asignación de consumo aplicado.": "consultar_informe_asignacion",
    "Orden de servicio de verificación de uso indebido, cierre del servicio y la anulación del servicio.": "consultar_orden_servicio",
    "Liquidación emitida por el área comercial de la Empresa.": "consultar_liquidacion",
    "Liquidación detallada del cobro por cierre o anulación de la conexión o reconexión indebida del servicio.": "consultar_liquidacion",
    "Meses adeudados.": "consultar_meses_adeudados",
    "Conceptos facturados luego del cierre.": "consultar_conceptos_facturados",
    "Documento que acredite la responsabilidad de otra persona respecto del pago de los meses reclamados.": "consultar_responsabilidad",
    "Acciones adoptadas por la Empresa Prestadora para su pago oportuno.": "consultar_acciones_cobranza",
    "Tipo y número de unidades de uso sobre las cuales ha venido siendo facturada la conexión en los seis (6) periodos anteriores al mes o meses reclamados.": "consultar_unidades_uso",
    "Croquis del predio detallando el número y ubicación de los puntos de agua y de desagüe.": "consultar_croquis",
    "Descripción detallada de la fachada del inmueble.": "consultar_croquis",
    "Croquis de la vivienda que incluya el sistema de agua potable y alcantarillado.": "consultar_croquis",
    "Avisos de cobranza con montos de cobranza.": "consultar_avisos_cobranza",
    "Documentación que sustente el cobro por los conceptos emitidos.": "consultar_documentacion_cobro",
    "Informe del área correspondiente de la Empresa Prestadora.": "consultar_informe_tecnico",
}


def obtener_tool_para_medio(medio: str) -> str | None:
    return MEDIO_TO_TOOL.get(medio)


def obtener_tools_para_medios(medios: list[str]) -> list[str]:
    tools = []
    for medio in medios:
        tool_name = obtener_tool_para_medio(medio)
        if tool_name and tool_name not in tools:
            tools.append(tool_name)
    return tools
