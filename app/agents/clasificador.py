import json

from app.agents.analizador import AnalizadorAgent


def clasificar_reclamo(
    suministro_id: str,
    reclamo_id: str,
    detalle: str,
    modelo: str | None = None,
):

    analizador = AnalizadorAgent()
    analisis = analizador.run(detalle)

    clasificacion = " / ".join(
        filter(
            None,
            [
                analisis.get("categoria", ""),
                analisis.get("subcategoria", ""),
            ],
        )
    ) or "Sin clasificación"

    razonamiento = json.dumps(
        analisis,
        ensure_ascii=False,
        indent=2,
    )

    return {
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "clasificacion": clasificacion,
        "razonamiento": razonamiento,
    }
