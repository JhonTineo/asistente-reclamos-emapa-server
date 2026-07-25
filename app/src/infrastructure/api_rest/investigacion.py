import asyncio
import time
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService
from starlette.concurrency import run_in_threadpool
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.infrastructure.api_rest.schemas.investigacion import (
    InvestigacionRequest,
    InvestigacionResponse,
    ResumenMedio,
    ProblemaNormadoSchema,
    InformeRequest,
    InformeResponse,
    ProblemaInforme,
    BuscarReclamoRequest,
    BuscarReclamoResponse,
    ObjetivosRequest,
    ObjetivosResponse,
    ObjetivoInvestigacionSchema,
    MedioDisponible,
    ActualizarResumenRequest,
    ActualizarResumenResponse,
    ActualizarConclusionRequest,
    ActualizarConclusionResponse,
)
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.application.usecase.agents.objetivos import ObjetivosAgent
from app.src.application.usecase.agents.conclusion import ConclusionAgent

from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.services.investigacion.investigacion_service import (
    enfoque_para_medio, codigo_inspeccion_para_medio, medios_determinantes,
    analizar_medio_y_registrar,
)

logger = logging.getLogger("api.investigacion")


router = APIRouter(
    prefix="/investigacion",
    tags=["investigacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.post("/objetivos", response_model=ObjetivosResponse)
async def generar_objetivos(
    request: ObjetivosRequest,
    llm_router: LlmRouterService = Depends(get_llm_router)
) -> ObjetivosResponse:
    """Genera los objetivos de investigación a partir del motivo del reclamo
    (guardado al buscar el reclamo) y los deja en el informe. Se llama aparte de
    la búsqueda para poder correrlo en paralelo con la verificación de medios."""
    t_inicio = time.perf_counter()
    logger.info("[API /investigacion/objetivos] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}. Busque el reclamo primero.",
        )

    motivo = (informe.motivo or "").strip()
    logger.info(
        "[API /investigacion/objetivos] motivo_len=%d | clasificacion=%s",
        len(motivo), informe.clasificacion,
    )
    if motivo:
        agente = ObjetivosAgent(llm_router=llm_router, model=request.modelo)
        informe.objetivos = await run_in_threadpool(agente.generar, motivo, informe.clasificacion or "")
    else:
        informe.objetivos = []
        logger.warning(
            "[API /investigacion/objetivos] Reclamo %s SIN motivo guardado; no se infieren objetivos. "
            "¿Se buscó el reclamo (que guarda el motivo) después de reiniciar el server?",
            request.codreclamo,
        )

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/objetivos] COMPLETADO | objetivos=%d | tiempo=%.2fs",
        len(informe.objetivos), tiempo,
    )
    return ObjetivosResponse(
        codreclamo=request.codreclamo,
        objetivos=[ObjetivoInvestigacionSchema(**vars(o)) for o in informe.objetivos],
        tiempo=tiempo,
    )


@router.post("/inspeccion-externa", response_model=ResumenMedio, tags=["automatizacion"])
async def inspeccion_externa(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza la inspección externa y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "inspeccion_externa", "Inspección Externa", EmapaHttpAdapter(), llm_router)


@router.post("/inspeccion-interna", response_model=ResumenMedio, tags=["automatizacion"])
async def inspeccion_interna(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza la inspección interna y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "inspeccion_interna", "Inspección Interna", EmapaHttpAdapter(), llm_router)


@router.post("/tarjeta-lectura", response_model=ResumenMedio, tags=["automatizacion"])
async def tarjeta_lectura(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza la tarjeta de lecturas (micromedición) y registra su bloque.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "tarjeta_lectura", "Tarjeta de Lecturas", EmapaHttpAdapter(), llm_router)


@router.post("/corte-reapertura", response_model=ResumenMedio, tags=["automatizacion"])
async def corte_reapertura(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza los cortes/reaperturas y registra su bloque en el informe.
    Requiere que se haya analizado antes la tarjeta de lecturas (fija la
    ventana). Sin streaming: pensada para flujos automatizados."""
    return await analizar_medio_y_registrar(request, "corte_reapertura", "Cortes y Reaperturas", EmapaHttpAdapter(), llm_router)


@router.post("/record-facturacion", response_model=ResumenMedio, tags=["automatizacion"])
async def record_facturacion(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza el record de facturación (cómo se facturó cada mes: por lectura o
    por promedio) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses). Sin streaming: pensada para
    flujos automatizados."""
    return await analizar_medio_y_registrar(request, "record_facturacion", "Record de Facturación", EmapaHttpAdapter(), llm_router)


@router.post("/saldo-detalle", response_model=ResumenMedio, tags=["automatizacion"])
async def saldo_detalle(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResumenMedio:
    """Analiza el saldo-detalle (pagos por mes: cobro indebido, mora y meses
    pendientes) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana). Sin streaming: flujos automatizados."""
    return await analizar_medio_y_registrar(request, "saldo_detalle", "Saldo Detalle", EmapaHttpAdapter(), llm_router)


@router.post("/fundamentar-normativa", response_model=InformeResponse, tags=["automatizacion"])
async def fundamentar_normativa(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> InformeResponse:
    """Para cada problema detectado en los medios determinantes (ver
    ``medios_determinantes``), busca normativa y consulta al LLM qué procede hacer.
    Sin streaming: pensada para flujos automatizados."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /investigacion/fundamentar-normativa] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if not informe:
        raise HTTPException(
            status_code=404, detail=f"No hay informe en curso para {request.codreclamo}",
        )
    if not informe.objetivos:
        raise HTTPException(
            status_code=400,
            detail="El informe no tiene objetivos. Ejecute /investigacion/objetivos primero.",
        )

    # Solo fundamenta los hallazgos de los medios marcados como determinantes
    # (los que deciden el veredicto).
    m_det = medios_determinantes(informe)
    if not m_det:
        logger.warning(
            "[API /investigacion/fundamentar-normativa] No hay objetivos "
            "determinantes. Se fundamentarán TODOS los problemas.",
        )
        problemas = informe.problemas
    else:
        logger.info("[API /investigacion/fundamentar-normativa] Medios determinantes: %s", m_det)
        problemas = [p for p in informe.problemas if p.medio_id in m_det]

    if not problemas:
        logger.info("[API /investigacion/fundamentar-normativa] Sin problemas para fundamentar")
    else:
        logger.info(
            "[API /investigacion/fundamentar-normativa] %d problema(s) a fundamentar",
            len(problemas),
        )
        fundamentador = FundamentacionNormativaAgent(qdrant=QdrantAdapter(), llm_router=llm_router, model=request.modelo)

        async def _fundamentar_uno(p):
            return await run_in_threadpool(fundamentador.fundamentar, p)

        problemas_fundamentados = await asyncio.gather(*[_fundamentar_uno(p) for p in problemas])
        for original, nuevo in zip(problemas, problemas_fundamentados):
            original.__dict__.update(nuevo.__dict__)

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/fundamentar-normativa] COMPLETADO | tiempo=%.2fs",
        tiempo,
    )
    logger.info("=" * 60)
    return InformeResponse(
        codreclamo=informe.reclamo,
        suministro=informe.suministro,
        clasificacion=informe.clasificacion,
        objetivos=[ObjetivoInvestigacionSchema(**vars(o)) for o in informe.objetivos] if informe.objetivos else [],
        problemas=[ProblemaInforme(**vars(p)) for p in informe.problemas],
        tiempo=tiempo,
    )


@router.post("/conclusion", response_model=InformeResponse, tags=["automatizacion"])
async def re_generar_conclusion(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> InformeResponse:
    """Evalúa los objetivos de investigación contra los hallazgos (problemas +
    datos) para decidir el veredicto (FUNDADO/INFUNDADO). Opcionalmente regenera
    el texto de la conclusión del informe. Sin streaming."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /investigacion/conclusion] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if not informe:
        raise HTTPException(
            status_code=404, detail=f"No hay informe en curso para {request.codreclamo}",
        )
    if not informe.objetivos:
        raise HTTPException(
            status_code=400,
            detail="El informe no tiene objetivos. Ejecute /investigacion/objetivos primero.",
        )

    agente = ConclusionAgent(llm_router=llm_router, model=request.modelo)
    clasificacion = request.clasificacion or informe.clasificacion or ""
    fundamentador = FundamentacionNormativaAgent(
        qdrant=QdrantAdapter(), llm_router=llm_router, model=request.modelo,
    )
    problemas_resp: list[ProblemaInforme] = []
    medios_det = medios_determinantes(informe)
    total_a_fundamentar = sum(
        len(b.problemas) for b in informe.bloques if not medios_det or b.medio_id in medios_det
    )
    logger.info(
        "[API /investigacion/conclusion] Fundamentando %d problema(s) de medios "
        "determinantes %s (de %d bloque(s))",
        total_a_fundamentar, sorted(medios_det) or "TODOS", len(informe.bloques),
    )
    idx = 0
    for bloque in informe.bloques:
        fundamentar_medio = not medios_det or bloque.medio_id in medios_det
        for problema in bloque.problemas:
            if fundamentar_medio:
                idx += 1
                logger.info(
                    "[API /investigacion/conclusion] Problema %d/%d | medio=%s | tipo=%s",
                    idx, total_a_fundamentar, bloque.medio_id, problema.tipo,
                )
                fundamentador.fundamentar(problema, clasificacion, contexto=informe.motivo or "")
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

    # Conclusión: veredicto FUNDADO/INFUNDADO por regla sobre los objetivos.
    veredicto = ConclusionAgent(llm_router=llm_router, model=request.modelo).concluir_y_asignar(informe)

    texto = construir_texto_informe(informe)

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/conclusion] COMPLETADO | veredicto=%s | bloques=%d | problemas=%d | tiempo=%.2fs",
        veredicto, len(informe.bloques), len(problemas_resp), tiempo,
    )
    logger.info("=" * 60)

    return InformeResponse(
        codreclamo=request.codreclamo,
        informe=texto,
        problemas=problemas_resp,
        tiempo=tiempo,
    )





@router.patch("/{medio}/resumen", response_model=ActualizarResumenResponse)
async def actualizar_resumen(medio: str, request: ActualizarResumenRequest) -> ActualizarResumenResponse:
    """
    Edita a mano el resumen (texto narrativo) de un medio ya analizado, sin
    tocar los problemas detectados ni invocar al LLM. No borra la conclusión,
    propuesta o resolución ya generadas: el usuario decide si las edita él
    mismo o las vuelve a generar con este resumen actualizado. Devuelve el
    informe re-renderizado para refrescar la sección de informe de atención.
    """
    medio_id = medio.replace("-", "_")
    actualizado = informe_store.actualizar_resumen(request.codreclamo, medio_id, request.resumen)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un bloque analizado para el medio '{medio}' en el reclamo {request.codreclamo}.",
        )
    informe = informe_store.obtener(request.codreclamo)
    return ActualizarResumenResponse(
        codreclamo=request.codreclamo,
        medio_id=medio_id,
        resumen=request.resumen,
        informe_texto=construir_texto_informe(informe),
    )


@router.patch("/conclusion", response_model=ActualizarConclusionResponse)
async def actualizar_conclusion(request: ActualizarConclusionRequest) -> ActualizarConclusionResponse:
    """
    Edita a mano el párrafo de conclusión, sin tocar el veredicto ni invocar
    al LLM. Devuelve el informe re-renderizado para refrescar la sección de
    informe de atención con el nuevo texto.
    """
    actualizado = informe_store.actualizar_conclusion(request.codreclamo, request.conclusion)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    informe = informe_store.obtener(request.codreclamo)
    return ActualizarConclusionResponse(
        codreclamo=request.codreclamo,
        conclusion=request.conclusion,
        informe_texto=construir_texto_informe(informe),
    )


