"""Endpoints de streaming (NDJSON) del proceso de Investigación: las versiones
"en vivo" de los medios probatorios y de la conclusión, pensadas para que el
frontend muestre progreso mientras el usuario mira la pantalla. Sus
equivalentes sin streaming (para flujos automatizados) viven en
`investigacion.py`; ambos comparten la lógica de
application/services/investigacion/investigacion_service.py
(`stream_analisis_medio`, `medios_determinantes`).

Mismo prefix ("/investigacion") y las mismas dependencias que el router de
investigacion.py: para el frontend y para EMAPA es el mismo proceso, solo se
separó el archivo por tamaño (streaming vs. sync)."""

import time
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.application.services.investigacion.investigacion_service import (
    stream_analisis_medio,
)
from app.src.application.services.investigacion.fundamentacion_service import (
    fundamentar_normativa_stream,
)
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoRequest,
    InformeRequest,
    ProblemaInforme,
)
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe

logger = logging.getLogger("api.investigacion_stream")

router = APIRouter(
    prefix="/investigacion",
    tags=["investigacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.post("/inspeccion-externa/stream", tags=["interactivo"])
async def inspeccion_externa_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_externa", "Inspección Externa", EmapaHttpAdapter(), llm_router)


@router.post("/inspeccion-interna/stream", tags=["interactivo"])
async def inspeccion_interna_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_interna", "Inspección Interna", EmapaHttpAdapter(), llm_router)


@router.post("/tarjeta-lectura/stream", tags=["interactivo"])
async def tarjeta_lectura_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "tarjeta_lectura", "Tarjeta de Lecturas", EmapaHttpAdapter(), llm_router)


@router.post("/corte-reapertura/stream", tags=["interactivo"])
async def corte_reapertura_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "corte_reapertura", "Cortes y Reaperturas", EmapaHttpAdapter(), llm_router)


@router.post("/record-facturacion/stream", tags=["interactivo"])
async def record_facturacion_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "record_facturacion", "Record de Facturación", EmapaHttpAdapter(), llm_router)


@router.post("/saldo-detalle/stream", tags=["interactivo"])
async def saldo_detalle_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "saldo_detalle", "Saldo Detalle", EmapaHttpAdapter(), llm_router)


@router.post("/fundamentar-normativa/stream", tags=["interactivo"])
async def fundamentar_normativa_stream_endpoint(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Fundamentación normativa en streaming (NDJSON). Emite, a medida que se
    producen: ``candidatos`` (hallazgos determinantes seleccionados),
    ``articulos`` (por hallazgo) y ``fundamentacion`` (el párrafo final, que se
    guarda en el informe y se renderiza antes de la conclusión).
    Se ejecuta entre el análisis de los medios y la conclusión."""
    return fundamentar_normativa_stream(request, llm_router)


@router.post("/conclusion/stream", tags=["interactivo"])
async def generar_conclusion_stream(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Concluye el informe en streaming (NDJSON). Evalúa los objetivos
    determinantes contra sus hallazgos (puerta lógica) y consume el párrafo de
    fundamentación ya generado (paso /fundamentar-normativa); NO vuelve a
    fundamentar por problema. Emite:

    1. ``conclusion``: veredicto (FUNDADO/INFUNDADO) y su párrafo.
    2. ``informe``: el texto en lenguaje natural ya armado.

    Pensada para uso interactivo (el frontend muestra progreso en vivo).
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info("[API /investigacion/conclusion/stream] codreclamo=%s", request.codreclamo)

        informe = informe_store.obtener(request.codreclamo)
        if informe is None:
            yield json.dumps({
                "evento": "error",
                "error": (
                    f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                    "Busque el reclamo y analice al menos un medio antes de concluirlo."
                ),
            }, ensure_ascii=False) + "\n"
            return

        # La fundamentación normativa YA se realizó en su propio paso
        # (/investigacion/fundamentar-normativa) y quedó guardada en el informe;
        # aquí la conclusión la consume, sin volver a fundamentar por problema.
        problemas_resp: list[ProblemaInforme] = [
            ProblemaInforme(
                medio_id=bloque.medio_id,
                tipo=problema.tipo,
                detalle=problema.detalle,
                accion=problema.accion,
                responsable=problema.responsable,
                base_legal=problema.base_legal,
            )
            for bloque in informe.bloques
            for problema in bloque.problemas
        ]

        try:
            # --- Conclusión: veredicto FUNDADO/INFUNDADO ----------------------
            conclusionador = ConclusionAgent(llm_router=llm_router, model=request.modelo)
            veredicto = await run_in_threadpool(conclusionador.concluir_y_asignar, informe)
            yield json.dumps({
                "evento": "conclusion",
                "veredicto": veredicto,
                "conclusion": informe.conclusion,
            }, ensure_ascii=False) + "\n"

            # --- Cierre: texto final del informe ------------------------------
            texto = construir_texto_informe(informe)
            tiempo = time.perf_counter() - t_inicio
            yield json.dumps({
                "evento": "informe",
                "codreclamo": request.codreclamo,
                "informe": texto,
                "problemas": [p.model_dump() for p in problemas_resp],
                "tiempo": tiempo,
            }, ensure_ascii=False) + "\n"

            logger.info(
                "[API /investigacion/conclusion/stream] COMPLETADO | bloques=%d | problemas=%d | tiempo=%.2fs",
                len(informe.bloques), len(problemas_resp), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/conclusion/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")

