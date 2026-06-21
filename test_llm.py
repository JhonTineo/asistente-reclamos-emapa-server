"""
Script de prueba para validar la conexión con OpenCode Go + GLM-5
y la clasificación de reclamos.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv()

from app.core.llm import get_llm
from app.agents.clasificador import clasificar_reclamo


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


if __name__ == "__main__":
    api_key = os.getenv("OPENCODE_GO_API_KEY", "")
    if not api_key or "tu-key" in api_key:
        print("ERROR: Debes configurar tu API key en el archivo .env")
        print("       Edita .env y reemplaza 'sk-or-v1-tu-key-de-opencode-zen'")
        sys.exit(1)

    test_conexion()
    test_clasificacion()
