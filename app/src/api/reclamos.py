import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.src.agents.analizador import AnalizadorAgent
from app.src.agents.clasificador_llm import clasificar_reclamo as clasificar_llm

logger = logging.getLogger("api.clasificador")

router = APIRouter(prefix="/reclamos", tags=["reclamos"])


class ClasificarResponse(BaseModel):
    reclamo_id: str
    suministro_id: str
    clasificacion: str
    descripcion: str | None
    score: float


class ClasificarLLMRequest(BaseModel):
    detalle: str


class ClasificarLLMResponse(BaseModel):
    success: bool
    codigo: str | None
    nombre: str | None
    seccion: str | None
    error: str | None

analizador = AnalizadorAgent()

@router.post("/clasificar", response_model=ClasificarResponse)
def clasificar(request: dict) -> ClasificarResponse:
    suministro_id = request.get("suministro_id", "N/A")
    reclamo_id = request.get("reclamo_id", "N/A")
    detalle = request.get("detalle", "")

    t1 = time.perf_counter()
    analisis = analizador.run(detalle)
    t2 = time.perf_counter()
    logger.info(f"Tiempo clasificación del reclamo: {t1 - t2:.4f} segundos")

    return ClasificarResponse(
        reclamo_id=reclamo_id,
        suministro_id=suministro_id,
        clasificacion=analisis["categoria_probable"],
        descripcion=analisis["descripcion"],
        score=analisis["score"]
    )


@router.post("/clasificar-llm", response_model=ClasificarLLMResponse)
def clasificar_con_llm(request: ClasificarLLMRequest) -> ClasificarLLMResponse:
    resultado = clasificar_llm(detalle=request.detalle)

    if not resultado["success"]:
        raise HTTPException(status_code=500, detail=resultado.get("error", "Error desconocido"))

    return ClasificarLLMResponse(**resultado)
