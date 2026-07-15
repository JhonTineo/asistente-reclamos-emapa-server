import json
import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.src.application.usecase.agents.analizador import AnalizadorAgent
from app.src.application.usecase.agents.clasificador_llm import clasificar_reclamo as clasificar_llm
from app.src.core.schemas.investigacion import BuscarReclamoResponse
from app.src.core.service.tools.emapa_client import consultar_emapa

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

@router.get("/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}", response_model=BuscarReclamoResponse)
async def buscar_reclamo(codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> BuscarReclamoResponse:
    """
    Busca los datos de un reclamo en el sistema de EMAPA.
    """
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /reclamo] Buscando reclamo")
    logger.info("[API /reclamo] codsede=%s | codsuc=%s | codcliente=%s | codreclamo=%s",
                codsede, codsuc, codcliente, codreclamo)
    result = consultar_emapa(
        endpoint_key="buscar_reclamo",
        params={"codsede": codsede, "codsuc": codsuc, "codreclamo": codreclamo, "codcliente": codcliente}
    )
    tiempo = time.perf_counter() - t_inicio
    if result.success:
        try:
            datos = json.loads(result.data) if result.data else None
            logger.info("[API /reclamo] OK | tiempo=%.2fs", tiempo)
            logger.info("=" * 60)
            return BuscarReclamoResponse(
                codreclamo=codreclamo,
                datos=datos,
                tiempo=tiempo,
            )
        except json.JSONDecodeError as e:
            logger.error("[API /reclamo] Error al parsear respuesta: %s", str(e))
            logger.info("=" * 60)
            return BuscarReclamoResponse(
                codreclamo=codreclamo,
                datos=None,
                error=f"Error al parsear respuesta: {str(e)}",
                tiempo=tiempo,
            )
    else:
        logger.error("[API /reclamo] Error: %s", result.error)
        logger.info("=" * 60)
        return BuscarReclamoResponse(
            codreclamo=codreclamo,
            datos=None,
            error=result.error,
            tiempo=tiempo,
        )


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
