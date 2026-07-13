# -*- coding: utf-8 -*-
"""
Test del flujo servidor del informe de atención, SIN llamar a EMAPA:

  1. crear_metadata        (equivale a "buscar reclamo")
  2. registrar_bloque × N  (equivale a analizar cada medio; bloques sintéticos)
  3. fundamentar + render  (equivale a POST /investigacion/informe)

Requiere Qdrant + Ollama arriba (para la fundamentación normativa).
    OLLAMA_BASE_URL=http://localhost:11434 QDRANT_URL=http://localhost:6333 \
        .venv/Scripts/python.exe app/test/test_informe_flujo.py
"""

import os
import sys

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from app.src.core.model.informe_atencion import BloqueMedio, ProblemaNormado
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.usecase.agents.fundamentacion_normativa import (
    FundamentacionNormativaAgent,
)

CODRECLAMO = "233607"
CODCLIENTE = "12882"


def main():
    # 1) buscar reclamo -> metadatos
    informe = informe_store.crear_metadata(
        codreclamo=CODRECLAMO,
        suministro=CODCLIENTE,
        clasificacion="facturación excesiva",
    )
    print(f"1) Metadatos creados: informe {informe.numero}")

    # 2) análisis de medios -> bloques (sintéticos, como los daría AnalistaMedioAgent)
    #    - inspección interna SIN problemas (frase predefinida)
    informe_store.registrar_bloque(CODRECLAMO, BloqueMedio(
        medio_id="inspeccion_interna",
        medio_nombre="Inspección Interna",
        entidad={},
        resumen="Realizada la inspección interna no se encontró ningún problema.",
        problemas=[],
    ))
    #    - tarjeta de lecturas CON problemas
    informe_store.registrar_bloque(CODRECLAMO, BloqueMedio(
        medio_id="tarjeta_lectura",
        medio_nombre="Tarjeta de Lecturas",
        entidad={},
        resumen="En el periodo reclamado se observan consumos que requieren revisión.",
        problemas=[
            ProblemaNormado(tipo="errorConsumo",
                            detalle="2022-11: consumo atípico (85 m³ > 2×promedio 30)"),
            ProblemaNormado(tipo="errorServicio",
                            detalle="2022-10: medidor: MEDIDOR INOPERATIVO"),
        ],
    ))
    print("2) Bloques registrados:", [b.medio_id for b in informe.bloques])

    # 3) generar informe -> fundamentar + render
    fundamentador = FundamentacionNormativaAgent()
    for bloque in informe.bloques:
        for problema in bloque.problemas:
            fundamentador.fundamentar(problema, informe.clasificacion or "")

    informe.conclusion = (
        "la facturación emitida es correcta y el reclamo se declara infundado."
    )

    texto = construir_texto_informe(informe)
    print("\n" + "=" * 90)
    print(texto)
    print("=" * 90)


if __name__ == "__main__":
    main()
