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
    ActualizarFundamentacionRequest,
    ActualizarFundamentacionResponse,
)
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.application.usecase.agents.objetivos import ObjetivosAgent
from app.src.application.usecase.agents.conclusion import ConclusionAgent

from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.services.investigacion.investigacion_service import (
    analizar_medio_y_registrar,
)
from app.src.application.services.investigacion.fundamentacion_service import (
    fundamentar_normativa_sync,
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
    """Selecciona 1-3 hallazgos determinantes (de los medios determinantes) con
    relación directa con el motivo y redacta UN párrafo de fundamentación
    normativa, que se guarda en el informe (se renderiza antes de la conclusión).
    Sin streaming: pensada para flujos automatizados."""
    resultado = await fundamentar_normativa_sync(request, llm_router)

    informe = informe_store.obtener(request.codreclamo)
    problemas = [
        ProblemaInforme(medio_id=b.medio_id, **{k: getattr(p, k) for k in ("tipo", "detalle", "seleccionado", "articulos", "accion", "responsable", "base_legal")})
        for b in informe.bloques for p in b.problemas
    ]
    return InformeResponse(
        codreclamo=informe.reclamo,
        suministro=informe.suministro,
        clasificacion=informe.clasificacion,
        objetivos=[ObjetivoInvestigacionSchema(**vars(o)) for o in informe.objetivos] if informe.objetivos else [],
        problemas=problemas,
        fundamentacion=resultado.get("fundamentacion"),
        tiempo=resultado.get("tiempo", 0.0),
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

    # La fundamentación normativa YA se realizó en su propio paso
    # (/investigacion/fundamentar-normativa) y quedó guardada en el informe; la
    # conclusión la consume, sin volver a fundamentar por problema.
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


@router.patch("/fundamentar-normativa", response_model=ActualizarFundamentacionResponse)
async def actualizar_fundamentacion(request: ActualizarFundamentacionRequest) -> ActualizarFundamentacionResponse:
    """
    Edita a mano el párrafo de fundamentación normativa, sin re-seleccionar
    problemas ni invocar al LLM. Devuelve el informe re-renderizado.
    """
    actualizado = informe_store.actualizar_fundamentacion(request.codreclamo, request.fundamentacion)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    informe = informe_store.obtener(request.codreclamo)
    return ActualizarFundamentacionResponse(
        codreclamo=request.codreclamo,
        fundamentacion=request.fundamentacion,
        informe_texto=construir_texto_informe(informe),
    )


