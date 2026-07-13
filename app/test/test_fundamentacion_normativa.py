# -*- coding: utf-8 -*-
"""
Test del agente de fundamentación normativa para TARJETA DE LECTURAS.

Ejercita: normalizador de problemas -> búsqueda vectorial (Qdrant) ->
inferencia del LLM (acción + responsable + base legal).

No usa la API de EMAPA: arma una TargetaLecturas sintética con hallazgos.

Requiere Qdrant y Ollama arriba. Ejecutar con el .venv del proyecto:
    OLLAMA_BASE_URL=http://localhost:11434 QDRANT_URL=http://localhost:6333 \
        .venv/Scripts/python.exe app/test/test_fundamentacion_normativa.py
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

from app.src.core.model.targeta_lecturas import TargetaLecturas
from app.src.application.services.pre_proces.problemas_normalizer import (
    problemas_de_targeta,
)
from app.src.application.usecase.agents.fundamentacion_normativa import (
    FundamentacionNormativaAgent,
)


def main():
    # Tarjeta sintética con hallazgos típicos (como los produce el
    # preprocesamiento real).
    targeta = TargetaLecturas(
        codcliente="12882",
        errorConsumo=[
            "2022-11: consumo atípico (85 m³ > 2×promedio 30)",
        ],
        errorLecturas=[
            "2022-12: consumo negativo (última 340 < anterior 355)",
        ],
        errorServicio=[
            "2022-10: medidor: MEDIDOR INOPERATIVO",
        ],
    )

    print("PASO A: normalizar problemas de la tarjeta")
    problemas = problemas_de_targeta(targeta)
    print(f"  problemas detectados: {len(problemas)}")
    for p in problemas:
        print(f"    - [{p.tipo}] {p.detalle}")

    print("\nPASO B: fundamentar cada problema (búsqueda + LLM)")
    agente = FundamentacionNormativaAgent()
    agente.fundamentar_todos(problemas, clasificacion="facturación excesiva")

    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    for p in problemas:
        print(f"\n■ Problema [{p.tipo}]: {p.detalle}")
        arts = ", ".join(
            f"Art.{a['numeral'] or a['article']}(score={a['score']})"
            for a in p.articulos
        ) or "(sin artículos sobre el umbral)"
        print(f"  Artículos recuperados: {arts}")
        print(f"  Responsable : {p.responsable}")
        print(f"  Base legal  : {p.base_legal}")
        print(f"  Acción      : {p.accion}")


if __name__ == "__main__":
    main()
