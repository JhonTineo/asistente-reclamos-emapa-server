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

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm
from app.src.application.services.investigacion.investigacion_service import (
    medios_determinantes,
    stream_analisis_medio,
)
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoRequest,
    InformeRequest,
    ProblemaInforme,
)
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
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
async def inspeccion_externa_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_externa", "Inspección Externa")


@router.post("/inspeccion-interna/stream", tags=["interactivo"])
async def inspeccion_interna_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_interna", "Inspección Interna")


@router.post("/tarjeta-lectura/stream", tags=["interactivo"])
async def tarjeta_lectura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/corte-reapertura/stream", tags=["interactivo"])
async def corte_reapertura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/record-facturacion/stream", tags=["interactivo"])
async def record_facturacion_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "record_facturacion", "Record de Facturación")


@router.post("/saldo-detalle/stream", tags=["interactivo"])
async def saldo_detalle_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "saldo_detalle", "Saldo Detalle")


@router.post("/conclusion/stream", tags=["interactivo"])
async def generar_conclusion_stream(request: InformeRequest) -> StreamingResponse:
    """Concluye el informe en streaming (NDJSON). Por cada problema de cada medio
    emite dos eventos a medida que se producen:

    1. ``articulos``: los artículos SUNASS recuperados para ese problema.
    2. ``fundamentacion``: la inferencia del LLM (acción, responsable, base legal).

    Al final emite ``informe`` con el texto en lenguaje natural ya armado.
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

        clasificacion = request.clasificacion or informe.clasificacion or ""

        # Solo se fundamentan los hallazgos de los medios DETERMINANTES (los que
        # deciden el veredicto); los demás se incluyen sin fundamentar. Si no hay
        # determinantes, se fundamenta todo (respaldo).
        medios_det = medios_determinantes(informe)
        total = sum(
            len(b.problemas) for b in informe.bloques if not medios_det or b.medio_id in medios_det
        )
        yield json.dumps({"evento": "inicio", "total_problemas": total}, ensure_ascii=False) + "\n"

        fundamentador = FundamentacionNormativaAgent(model=request.modelo)
        problemas_resp: list[ProblemaInforme] = []
        indice = 0

        try:
            for bloque in informe.bloques:
                fundamentar_medio = not medios_det or bloque.medio_id in medios_det
                for problema in bloque.problemas:
                    if fundamentar_medio:
                        # --- Fase 1: recuperación de artículos -------------------
                        articulos = await run_in_threadpool(
                            fundamentador.fundamentar_articulos, problema, informe.motivo or "",
                        )
                        yield json.dumps({
                            "evento": "articulos",
                            "indice": indice,
                            "medio_id": bloque.medio_id,
                            "tipo": problema.tipo,
                            "detalle": problema.detalle,
                            "articulos": problema.articulos,
                        }, ensure_ascii=False) + "\n"

                        # --- Fase 2: inferencia del LLM --------------------------
                        await run_in_threadpool(
                            fundamentador.fundamentar_interpretacion,
                            problema, articulos, clasificacion, informe.motivo or "",
                        )
                        yield json.dumps({
                            "evento": "fundamentacion",
                            "indice": indice,
                            "medio_id": bloque.medio_id,
                            "tipo": problema.tipo,
                            "detalle": problema.detalle,
                            "accion": problema.accion,
                            "responsable": problema.responsable,
                            "base_legal": problema.base_legal,
                        }, ensure_ascii=False) + "\n"
                        indice += 1

                    problemas_resp.append(
                        ProblemaInforme(
                            medio_id=bloque.medio_id,
                            tipo=problema.tipo,
                            detalle=problema.detalle,
                            accion=problema.accion,
                            responsable=problema.responsable,
                            base_legal=problema.base_legal,
                        )
                    )

            # --- Conclusión: veredicto FUNDADO/INFUNDADO ----------------------
            conclusionador = ConclusionAgent(model=request.modelo)
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

