import time
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm
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
async def generar_objetivos(request: ObjetivosRequest) -> ObjetivosResponse:
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
        agente = ObjetivosAgent(model=request.modelo)
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
async def inspeccion_externa(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección externa y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "inspeccion_externa", "Inspección Externa")


@router.post("/inspeccion-interna", response_model=ResumenMedio, tags=["automatizacion"])
async def inspeccion_interna(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección interna y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "inspeccion_interna", "Inspección Interna")


@router.post("/tarjeta-lectura", response_model=ResumenMedio, tags=["automatizacion"])
async def tarjeta_lectura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la tarjeta de lecturas (micromedición) y registra su bloque.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await analizar_medio_y_registrar(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/corte-reapertura", response_model=ResumenMedio, tags=["automatizacion"])
async def corte_reapertura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza los cortes/reaperturas y registra su bloque en el informe.
    Requiere que se haya analizado antes la tarjeta de lecturas (fija la
    ventana). Sin streaming: pensada para flujos automatizados."""
    return await analizar_medio_y_registrar(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/record-facturacion", response_model=ResumenMedio, tags=["automatizacion"])
async def record_facturacion(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el record de facturación (cómo se facturó cada mes: por lectura o
    por promedio) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses). Sin streaming: pensada para
    flujos automatizados."""
    return await analizar_medio_y_registrar(request, "record_facturacion", "Record de Facturación")


@router.post("/saldo-detalle", response_model=ResumenMedio, tags=["automatizacion"])
async def saldo_detalle(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el saldo-detalle (pagos por mes: cobro indebido, mora y meses
    pendientes) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses). Sin streaming: pensada
    para flujos automatizados."""
    return await analizar_medio_y_registrar(request, "saldo_detalle", "Saldo Detalle")


@router.post("/conclusion", response_model=InformeResponse, tags=["automatizacion"])
async def generar_conclusion(request: InformeRequest) -> InformeResponse:
    """
    Concluye el informe de atención: recupera el informe (con los bloques ya
    llenados por cada medio), fundamenta normativamente cada problema
    detectado y devuelve el texto final en lenguaje natural. Sin streaming:
    pensada para flujos automatizados.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /investigacion/conclusion] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                "Busque el reclamo y analice al menos un medio antes de concluirlo."
            ),
        )

    clasificacion = request.clasificacion or informe.clasificacion or ""

    # Fase 4: fundamentación normativa. Solo se fundamentan los hallazgos de los
    # medios DETERMINANTES (los que deciden el veredicto); los demás se incluyen
    # sin fundamentar. Si no hay determinantes, se fundamenta todo (respaldo).
    fundamentador = FundamentacionNormativaAgent(model=request.modelo)
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
    veredicto = ConclusionAgent(model=request.modelo).concluir_y_asignar(informe)

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


