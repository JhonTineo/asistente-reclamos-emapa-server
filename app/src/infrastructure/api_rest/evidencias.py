"""Evidencias del veredicto: datos para graficar y fotos de SYSCO.

- GET /reclamos/{codreclamo}/evidencias        lectura pura de lo ya analizado
                                                (como /sustentacion): no llama a
                                                EMAPA ni al LLM.
- GET /reclamos/{codreclamo}/evidencias/fotos  fotos del medidor y de la
                                                inspección desde SYSCO. Exige el
                                                token de EMAPA de la petición
                                                (misma dependencia que la búsqueda
                                                del reclamo).
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from app.src.application.services.informe.evidencias import construir_evidencias
from app.src.application.services.informe.fotos_evidencia import FotosEvidenciaService
from app.src.application.services.informe.informe_store import informe_store
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.infrastructure.api_rest.deps import usar_token_emapa, requerir_token_emapa
from app.src.infrastructure.api_rest.schemas.evidencias import EvidenciasResponse, FotosEvidenciaResponse

logger = logging.getLogger("api.evidencias")

router = APIRouter(prefix="/reclamos", tags=["evidencias"], dependencies=[Depends(usar_token_emapa)])


def _informe_o_404(codreclamo: str):
    informe = informe_store.obtener(codreclamo)
    if informe is None:
        raise HTTPException(status_code=404, detail=f"No hay un informe en curso para el reclamo {codreclamo}.")
    return informe


@router.get("/{codreclamo}/evidencias", response_model=EvidenciasResponse)
async def obtener_evidencias(codreclamo: str) -> EvidenciasResponse:
    """Serie de consumo mensual, indicadores del mes reclamado, lecturas,
    resultados de las inspecciones, línea de tiempo y verificaciones
    determinantes, a partir de los medios ya analizados en memoria."""
    informe = _informe_o_404(codreclamo)
    return EvidenciasResponse(**construir_evidencias(informe))


@router.get("/{codreclamo}/evidencias/fotos", response_model=FotosEvidenciaResponse)
async def obtener_fotos_evidencia(
    codreclamo: str,
    codsuc: str = Query(..., description="Sucursal del suministro (p.ej. 001)"),
    codcliente: str | None = Query(None, description="Suministro; por defecto el del informe"),
    refrescar: bool = Query(False, description="Ignorar la copia en memoria y volver a consultar SYSCO"),
    token: str = Depends(requerir_token_emapa),
) -> FotosEvidenciaResponse:
    """Fotos del medidor del mes reclamado, fotos de la inspección y formulario
    del reclamo. Sin firmas ni copias repetidas, reducidas a 1600 px."""
    informe = _informe_o_404(codreclamo)
    suministro = codcliente or informe.suministro

    def _consultar():
        adaptador = EmapaHttpAdapter()
        adaptador.set_token(token)  # el hilo no hereda el ContextVar de la petición
        return FotosEvidenciaService(adaptador).obtener(informe, codsuc, suministro, refrescar=refrescar)

    try:
        resultado = await run_in_threadpool(_consultar)
    except httpx.HTTPStatusError as exc:
        estado = exc.response.status_code if exc.response is not None else 502
        logger.warning("[API /evidencias/fotos] SYSCO respondió %s para el reclamo %s", estado, codreclamo)
        if estado in (401, 403):
            raise HTTPException(status_code=401, detail="EMAPA rechazó el token al pedir las fotos. Vuelve a iniciar sesión.")
        raise HTTPException(status_code=502, detail=f"SYSCO respondió con error {estado} al pedir las fotos.")
    except httpx.RequestError as exc:
        logger.warning("[API /evidencias/fotos] Sin respuesta de SYSCO: %s", exc)
        raise HTTPException(status_code=504, detail="SYSCO no respondió a tiempo al pedir las fotos.")
    return FotosEvidenciaResponse(**resultado)
