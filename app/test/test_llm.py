"""
Script de prueba para validar la conexión con OpenCode Go + GLM-5
y la clasificación de reclamos.
"""
import sys
import os
import json
from urllib import response
from dotenv import load_dotenv
from app.src.application.adapters.llm import get_llm
from app.src.application.usecase.agents.clasificador import ClasificadorAgent
from app.src.core.service.tools.emapa_api import (
    buscar_reclamo_emapa,
    obtener_saldo_actual,
    obtener_tarjeta_lectura,
    obtener_record_facturacion,
    obtener_corte_reapertura,
    obtener_inspeccion_externa,
    obtener_inspeccion_interna,
)
from app.src.application.usecase.workflow import ReclamoWorkflow

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

def _extraer_detalle_reclamo(payload):
    """Extrae texto útil del reclamo aunque la estructura del backend varíe."""
    return payload.get("data").get("motivo") + " observaciones " + payload.get("data").get("observaciones") if payload.get("data").get("observaciones") else "NINGUNA OBSERVACIÓN"

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
    resultado = ClasificadorAgent().run(
        detalle="""
                NO ESTOY CONFORME CON EL COBRO DE LOS RECIBOS DEL 2025 DE ENERO, FEBRERO, JUNIO, JULIO, AGOSTO, OCTUBRE, NOVIEMBRE Y DICIEMBRE, 
                YA QUE MIS CONSUMOS SON EN BASE A 23 M3 APROXIMADAMENTE Y ESO LO PUEDO REVISAR EN EL HISTORIAL DE MIS CONSUMOS, 
                POR LO QUE SOLICITOQ YUE REALICEN LAS INSPECCIONES QUE CORRESPONDA.
                """        
    )
    print(f"Tipo:     {resultado['tipo']}")
    print(f"Subtipo:  {resultado['subtipo']}")
    print(f"Justificación:   {resultado['justificacion']}")


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
        print(f"Claves raíz: {list(data_reclamo.keys())}")
    else:
        print(f"Tipo de respuesta: {type(data_reclamo).__name__}")
    detalle = _extraer_detalle_reclamo(data_reclamo)
    if not detalle:
        print("No se encontró campo de detalle en la respuesta; se usará JSON serializado.")
        detalle = json.dumps(data_reclamo, ensure_ascii=False)
    print(f"Detalle usado para clasificación (primeros 280 chars): {detalle[:280]}")
    resultado = ClasificadorAgent().run(
        detalle=detalle,
    )
    print(f"Tipo:     {resultado['tipo']}")
    print(f"Subtipo:  {resultado['subtipo']}")
    print(f"Justificación:   {resultado['justificacion']}")


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
    print(f"- Analisis: {json.dumps(resultado.get('analisis', {}), ensure_ascii=False)}")
    print(f"- Articulos recuperados: {len(resultado.get('articulos', []) or [])}")
    resumen = resultado.get("resumen_tecnico", "")
    if not isinstance(resumen, str):
        resumen = json.dumps(resumen, ensure_ascii=False)
    print(f"- Resumen tecnico (preview): {resumen}")
    dictamen = resultado.get("dictamen", {})
    if not isinstance(dictamen, dict):
        dictamen = {"raw": dictamen}
    print(f"- Dictamen (preview): {json.dumps(dictamen, ensure_ascii=False)}")
    print()


if __name__ == "__main__":
    test_workflow_reclamo_emapa_real()