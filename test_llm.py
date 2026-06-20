"""
Script de prueba para validar la conexión con OpenCode Go + GLM-5
y la clasificación de reclamos.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from app.core.llm import get_llm
from app.agents.clasificador import clasificar_reclamo
from app.tools.emapa_api import (
    buscar_reclamo_emapa,
    obtener_saldo_actual,
    obtener_tarjeta_lectura,
    obtener_record_facturacion,
    obtener_corte_reapertura,
    obtener_inspeccion_externa,
    obtener_inspeccion_interna,
)
from app.orchestrator.workflow import ReclamoWorkflow


def _extraer_detalle_reclamo(payload):
    """Extrae texto útil del reclamo aunque la estructura del backend varíe."""
    candidate_keys = (
        "detalle_reclamo",
        "detalle",
        "descripcion",
        "descripcion_reclamo",
        "observacion",
        "observaciones",
        "motivo",
    )

    if isinstance(payload, dict):
        for key in candidate_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in payload.values():
            extracted = _extraer_detalle_reclamo(value)
            if extracted:
                return extracted

    if isinstance(payload, list):
        for item in payload:
            extracted = _extraer_detalle_reclamo(item)
            if extracted:
                return extracted

    return ""


def _construir_contexto_emapa(codsede, codsuc, codreclamo, codcliente, anio="2025"):
    contexto_emapa = {}
    advertencias = []

    consultas = {
        "reclamo": lambda: buscar_reclamo_emapa(codsede, codsuc, codreclamo, codcliente),
        "saldo_actual": lambda: obtener_saldo_actual(codsuc, codcliente),
        "tarjeta_lectura": lambda: obtener_tarjeta_lectura(codsuc, codcliente),
        "record_facturacion": lambda: obtener_record_facturacion(codsuc, codcliente, anio),
        "corte_reapertura": lambda: obtener_corte_reapertura(codsuc, codcliente),
        "inspeccion_externa": lambda: obtener_inspeccion_externa(codsuc, codcliente),
        "inspeccion_interna": lambda: obtener_inspeccion_interna(codsuc, codcliente),
    }

    for clave, consulta in consultas.items():
        try:
            contexto_emapa[clave] = consulta()
        except Exception as exc:
            advertencias.append(f"{clave}: {exc}")

    return contexto_emapa, advertencias


def test_conexion():
    print("=" * 60)
    print("PRUEBA 1: Conexión directa al modelo")
    print("=" * 60)

    llm = get_llm()
    response = llm.invoke("Responde únicamente con la palabra 'OK' si me entiendes.")
    print(f"Respuesta del modelo: {response.content}")
    print()


def test_clasificacion():
    print("=" * 60)
    print("PRUEBA 2: Clasificación de reclamo")
    print("=" * 60)

    resultado = clasificar_reclamo(
        suministro_id="SUM-001",
        reclamo_id="REC-001",
        detalle="""
                NO ESTOY CONFORME CON EL COBRO DE LOS RECIBOS DEL 2025 DE ENERO, FEBRERO, JUNIO, JULIO, AGOSTO, OCTUBRE, NOVIEMBRE Y DICIEMBRE, 
                YA QUE MIS CONSUMOS SON EN BASE A 23 M3 APROXIMADAMENTE Y ESO LO PUEDO REVISAR EN EL HISTORIAL DE MIS CONSUMOS, 
                POR LO QUE SOLICITOQ YUE REALICEN LAS INSPECCIONES QUE CORRESPONDA.
                """,
    )

    print(f"ID Reclamo:     {resultado['reclamo_id']}")
    print(f"Clasificación:  {resultado['clasificacion']}")
    print(f"Razonamiento:   {resultado['razonamiento']}")
    print()


def test_clasificacion_reclamo_emapa_real():
    print("=" * 60)
    print("PRUEBA 3: Clasificación con reclamo real de EMAPA")
    print("=" * 60)

    codsede = "001"
    codsuc = "001"
    codreclamo = "249912"
    codcliente = "9732"

    data_reclamo = buscar_reclamo_emapa(
        codsede=codsede,
        codsuc=codsuc,
        codreclamo=codreclamo,
        codcliente=codcliente,
    )

    print("Respuesta cruda EMAPA (resumen):")
    if isinstance(data_reclamo, dict):
        print(f"Claves raíz: {list(data_reclamo.keys())[:10]}")
    else:
        print(f"Tipo de respuesta: {type(data_reclamo).__name__}")

    detalle = _extraer_detalle_reclamo(data_reclamo)
    if not detalle:
        print("No se encontró campo de detalle en la respuesta; se usará JSON serializado.")
        detalle = json.dumps(data_reclamo, ensure_ascii=False)

    print(f"Detalle usado para clasificación (primeros 280 chars): {detalle[:280]}")

    resultado = clasificar_reclamo(
        suministro_id=codcliente,
        reclamo_id=codreclamo,
        detalle=detalle,
    )

    print(f"ID Reclamo:     {resultado['reclamo_id']}")
    print(f"Clasificación:  {resultado['clasificacion']}")
    print(f"Razonamiento:   {resultado['razonamiento']}")
    print()


def test_workflow_reclamo_emapa_real():
    print("=" * 60)
    print("PRUEBA 4: Workflow completo con contexto EMAPA real")
    print("=" * 60)

    codsede = "001"
    codsuc = "001"
    codreclamo = "249912"
    codcliente = "9732"

    contexto_emapa, advertencias = _construir_contexto_emapa(
        codsede=codsede,
        codsuc=codsuc,
        codreclamo=codreclamo,
        codcliente=codcliente,
        anio="2025",
    )

    print(f"Fuentes EMAPA cargadas: {list(contexto_emapa.keys())}")
    if advertencias:
        print("Advertencias de carga EMAPA:")
        for warning in advertencias:
            print(f"- {warning}")

    data_reclamo = contexto_emapa.get("reclamo", {})
    detalle = _extraer_detalle_reclamo(data_reclamo)
    if not detalle:
        detalle = json.dumps(data_reclamo, ensure_ascii=False)

    workflow = ReclamoWorkflow()
    resultado = workflow.run(
        detalle=detalle,
        contexto_emapa=contexto_emapa,
    )

    print("Resumen de salida del workflow:")
    print(f"- Keys resultado: {list(resultado.keys())}")
    print(f"- Analisis: {json.dumps(resultado.get('analisis', {}), ensure_ascii=False)[:400]}")
    print(f"- Articulos recuperados: {len(resultado.get('articulos', []) or [])}")

    resumen = resultado.get("resumen_tecnico", "")
    if not isinstance(resumen, str):
        resumen = json.dumps(resumen, ensure_ascii=False)
    print(f"- Resumen tecnico (preview): {resumen[:400]}")

    dictamen = resultado.get("dictamen", {})
    if not isinstance(dictamen, dict):
        dictamen = {"raw": dictamen}
    print(f"- Dictamen (preview): {json.dumps(dictamen, ensure_ascii=False)[:500]}")
    print()


if __name__ == "__main__":
    api_key = os.getenv("OPENCODE_GO_API_KEY", "")
    if not api_key or "tu-key" in api_key:
        print("ADVERTENCIA: OPENCODE_GO_API_KEY no configurada.")
        print("            Se intentará usar el modelo local configurado en app.core.config.")

    test_conexion()
    test_clasificacion()
    test_clasificacion_reclamo_emapa_real()
    test_workflow_reclamo_emapa_real()
