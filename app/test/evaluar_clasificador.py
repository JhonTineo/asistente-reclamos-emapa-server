"""
Script de evaluación para el clasificador de reclamos.

Uso:
    python -m app.test.evaluar_clasificador

Requiere que la API esté corriendo en http://localhost:8000 o ajustar BASE_URL.
"""

import json
import requests
from pathlib import Path

BASE_URL = "http://localhost:8000"
ENDPOINT = f"{BASE_URL}/reclamos/clasificar"


def cargar_ejemplos():
    data_path = Path(__file__).parent / "data" / "reclamos_ejemplo.json"
    with open(data_path, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluar():
    ejemplos = cargar_ejemplos()
    correctos = 0
    scores = []

    for ejemplo in ejemplos:
        payload = {
            "reclamo_id": "eval-001",
            "suministro_id": "eval-001",
            "detalle": ejemplo["detalle"]
        }
        try:
            response = requests.post(ENDPOINT, json=payload, timeout=30)
            response.raise_for_status()
            resultado = response.json()
        except Exception as e:
            print(f"Error clasificando '{ejemplo['detalle'][:50]}...': {e}")
            continue

        tipo_predicho = resultado.get("clasificacion")
        score = resultado.get("score", 0.0)
        scores.append(score)

        acierto = tipo_predicho == ejemplo["tipo_esperado"]
        if acierto:
            correctos += 1

        print(f"Detalle: {ejemplo['detalle'][:60]}...")
        print(f"  Esperado: {ejemplo['tipo_esperado']}")
        print(f"  Predicho: {tipo_predicho} (score: {score:.4f})")
        print(f"  Acierto: {'SÍ' if acierto else 'NO'}")
        print()

    total = len(ejemplos)
    accuracy = correctos / total if total else 0.0
    score_promedio = sum(scores) / len(scores) if scores else 0.0

    print("=" * 50)
    print(f"Total evaluados: {total}")
    print(f"Aciertos: {correctos}")
    print(f"Precisión top-1: {accuracy:.2%}")
    print(f"Score promedio: {score_promedio:.4f}")


if __name__ == "__main__":
    evaluar()
