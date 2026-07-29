import logging
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from app.src.application.usecase.agents.clasificador_rapido import clasificar_rapido
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoResponse, InformeMetadata, ReclamoSchema,
    InformeCompletoResponse, ObjetivoInvestigacionSchema,
    ResumenMedio, ProblemaNormadoSchema, ProblemaInforme,
    SustentacionResponse,
    ObjetivosRequest, BuscarReclamoRequest, InformeRequest,
    IniciarInvestigacionRequest, IniciarInvestigacionResponse,
)
from app.src.infrastructure.api_rest.schemas.informe import (
    InformeAutomaticoRequest, InformeAutomaticoResponse,
)
from app.src.infrastructure.api_rest.schemas.reclamo import (
    ClasificarRapidoRequest, ClasificarRapidoResponse, FinalizarAtencionResponse,
)
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.infrastructure.adapters.http_client import EmapaSinDatosError
from app.src.application.services.informe.informe_store import informe_store, ReclamoEnAtencionError
from app.src.application.services.informe.render import construir_texto_informe
from app.src.application.services.informe.sustentacion import construir_sustentacion
from app.src.application.services.informe.informe_service import (
    buscar_y_crear_informe_o_lanzar, crear_informe_desde_datos,
)
from app.src.application.services.investigacion.investigacion_service import analizar_medios_en_paralelo
# Orquestador (POST /informe-atencion): reusa los pasos de investigación ya
# implementados ahí (objetivos, conclusión) en vez de duplicarlos. No hay
# import circular: investigacion.py no importa de acá.
from app.src.infrastructure.api_rest.investigacion import (
    generar_objetivos,
    re_generar_conclusion,
    fundamentar_normativa,
)
from app.src.infrastructure.api_rest.deps import usar_token_emapa, requerir_token_emapa, usar_config_llm

logger = logging.getLogger("api.clasificador")

router = APIRouter(prefix="/reclamos", tags=["reclamos"], dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)])


@router.get("/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}", response_model=BuscarReclamoResponse)
async def buscar_reclamo(
    codsede: str,
    codsuc: str,
    codreclamo: str,
    codcliente: str,
    sesion_id: str | None = Query(
        None,
        description=(
            "Identificador de la pestaña/sesión del frontend (p.ej. el id de la "
            "pestaña en la cola). Si otra sesión ya está atendiendo este reclamo, "
            "la búsqueda se rechaza con 409 en vez de pisar su avance."
        ),
    ),
    token: str = Depends(requerir_token_emapa),
) -> BuscarReclamoResponse:
    """
    Busca los datos de un reclamo en el sistema de EMAPA.

    El token de EMAPA (header Authorization) es OBLIGATORIO aquí: es el punto de
    entrada del flujo y con este token se harán las consultas de los pasos
    siguientes (investigación). Se guarda asociado al reclamo.
    """
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /reclamo] Buscando reclamo")
    logger.info("[API /reclamo] codsede=%s | codsuc=%s | codcliente=%s | codreclamo=%s",
                codsede, codsuc, codcliente, codreclamo)
    try:
        datos = EmapaHttpAdapter().buscar_reclamo(codsede, codsuc, codreclamo, codcliente)
    except EmapaSinDatosError:
        tiempo = time.perf_counter() - t_inicio
        logger.warning(
            "[API /reclamo] Reclamo no encontrado | codsede=%s codsuc=%s codcliente=%s codreclamo=%s",
            codsede, codsuc, codcliente, codreclamo,
        )
        logger.info("=" * 60)
        return BuscarReclamoResponse(
            codreclamo=codreclamo,
            datos=None,
            error=(
                "No se encontró el reclamo. Verifica el código de sede, sucursal, "
                "cliente y reclamo."
            ),
            tiempo=tiempo,
        )
    except Exception as e:  # noqa: BLE001
        tiempo = time.perf_counter() - t_inicio
        logger.error("[API /reclamo] Error: %s", str(e))
        logger.info("=" * 60)
        return BuscarReclamoResponse(
            codreclamo=codreclamo,
            datos=None,
            error=str(e),
            tiempo=tiempo,
        )

    tiempo = time.perf_counter() - t_inicio
    logger.info("[API /reclamo] OK | tiempo=%.2fs", tiempo)

    # Extracción de campos + entidad de dominio Reclamo + creación de metadatos
    # en el store (se guarda también el token para reutilizarlo en la
    # investigación). Mismo núcleo que usa POST /iniciar-investigacion.
    try:
        informe = crear_informe_desde_datos(datos, codreclamo, codcliente, token, sesion_id)
    except ReclamoEnAtencionError as e:
        logger.warning("[API /reclamo] %s", e)
        logger.info("=" * 60)
        raise HTTPException(status_code=409, detail=str(e))
    logger.info("=" * 60)
    return BuscarReclamoResponse(
        codreclamo=codreclamo,
        datos=datos,
        informe=InformeMetadata(
            numero=informe.numero,
            fecha=informe.fecha.isoformat(),
            asunto=informe.asunto,
            reclamo=informe.reclamo,
            suministro=informe.suministro,
            destinatario=informe.destinatario,
            datos_reclamo=ReclamoSchema(**vars(informe.datos_reclamo)) if informe.datos_reclamo else None,
        ),
        tiempo=tiempo,
    )


@router.post("/iniciar-investigacion", response_model=IniciarInvestigacionResponse)
async def iniciar_investigacion(
    request: IniciarInvestigacionRequest,
    token: str = Depends(requerir_token_emapa),
) -> IniciarInvestigacionResponse:
    """
    Arranca la investigación creando el informe de atención a partir del detalle
    del reclamo YA obtenido por el frontend (pantalla de detalle), SIN volver a
    consultar EMAPA.

    Hace exactamente lo mismo que GET /reclamo/{codsede}/{codsuc}/{codreclamo}/
    {codcliente} de la creación de la entidad de dominio en adelante (extrae los
    campos, arma el `Reclamo`, crea los metadatos y guarda el token), pero
    recibiendo el detalle en el cuerpo. Evita una segunda búsqueda del mismo
    reclamo, ya que la pantalla de detalle lo trajo con la misma consulta EMAPA.
    """
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info(
        "[API /iniciar-investigacion] codreclamo=%s | codcliente=%s",
        request.codreclamo, request.codcliente,
    )
    try:
        informe = crear_informe_desde_datos(
            request.datos, request.codreclamo, request.codcliente, token, request.sesion_id,
        )
    except ReclamoEnAtencionError as e:
        logger.warning("[API /iniciar-investigacion] %s", e)
        logger.info("=" * 60)
        raise HTTPException(status_code=409, detail=str(e))

    tiempo = time.perf_counter() - t_inicio
    logger.info("[API /iniciar-investigacion] OK | tiempo=%.2fs", tiempo)
    logger.info("=" * 60)
    return IniciarInvestigacionResponse(
        codreclamo=request.codreclamo,
        informe=InformeMetadata(
            numero=informe.numero,
            fecha=informe.fecha.isoformat(),
            asunto=informe.asunto,
            reclamo=informe.reclamo,
            suministro=informe.suministro,
            destinatario=informe.destinatario,
            datos_reclamo=ReclamoSchema(**vars(informe.datos_reclamo)) if informe.datos_reclamo else None,
        ),
        tiempo=tiempo,
    )


@router.post("/clasificar-rapido", response_model=ClasificarRapidoResponse)
def clasificar_rapido_endpoint(request: ClasificarRapidoRequest) -> ClasificarRapidoResponse:
    """
    Clasificación rápida por reglas (sin LLM ni embeddings), pensada para
    reclamos web. Si el reclamo ya trae tipo asignado (des_cod_reclamo), se
    respeta y no se reclasifica.
    """
    if request.des_cod_reclamo and request.des_cod_reclamo.strip():
        return ClasificarRapidoResponse(
            tipo=request.des_cod_reclamo.strip(),
            confianza="definida",
            metodo="sistema",
        )

    resultado = clasificar_rapido(request.motivo, request.desc_tipo_reclamo)
    return ClasificarRapidoResponse(
        tipo=resultado["tipo"],
        confianza=resultado["confianza"],
        metodo=resultado["metodo"],
        score=resultado["score"],
        candidatos=resultado["candidatos"],
    )


@router.get("/{codreclamo}/informe", response_model=InformeCompletoResponse)
async def obtener_informe_completo(codreclamo: str) -> InformeCompletoResponse:
    """
    Lectura pura del informe en curso (sin efectos secundarios: no crea nada,
    no llama al LLM, no toca el dueño de la sesión). Devuelve todo lo que hay
    en memoria para este reclamo — bloques analizados, objetivos, conclusión,
    propuesta y resolución — para que el frontend pueda reconstruir su estado
    tras recargar la página. 404 si no hay nada en memoria (p.ej. el servidor
    se reinició, o el informe ya se cerró con DELETE).
    """
    informe = informe_store.obtener(codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {codreclamo}.",
        )

    resumenes = [
        ResumenMedio(
            medio_id=b.medio_id,
            medio_nombre=b.medio_nombre,
            resumen=b.resumen,
            datos=b.entidad,
            problemas=[ProblemaNormadoSchema(**vars(p)) for p in b.problemas],
        )
        for b in informe.bloques
    ]
    problemas = [
        ProblemaInforme(
            medio_id=b.medio_id,
            tipo=p.tipo,
            detalle=p.detalle,
            accion=p.accion,
            responsable=p.responsable,
            base_legal=p.base_legal,
        )
        for b in informe.bloques
        for p in b.problemas
    ]

    return InformeCompletoResponse(
        codreclamo=codreclamo,
        informe=InformeMetadata(
            numero=informe.numero,
            fecha=informe.fecha.isoformat(),
            asunto=informe.asunto,
            reclamo=informe.reclamo,
            suministro=informe.suministro,
            destinatario=informe.destinatario,
            datos_reclamo=ReclamoSchema(**vars(informe.datos_reclamo)) if informe.datos_reclamo else None,
        ),
        objetivos=[ObjetivoInvestigacionSchema(**vars(o)) for o in informe.objetivos],
        resumenes=resumenes,
        ventana_meses=informe.ventana_meses,
        veredicto=informe.veredicto,
        conclusion=informe.conclusion,
        problemas=problemas,
        propuesta_conciliacion=(
            informe.propuesta_conciliacion.propuesta_empresa
            if informe.propuesta_conciliacion else None
        ),
        resolucion=informe.resolucion,
        informe_texto=construir_texto_informe(informe),
    )


@router.get("/{codreclamo}/sustentacion", response_model=SustentacionResponse)
async def obtener_sustentacion(codreclamo: str) -> SustentacionResponse:
    """
    Ensambla el Informe de Sustentación del Régimen de Facturación a partir de
    lo ya analizado en memoria (tarjeta de lecturas + record de facturación +
    datos del reclamo). Lectura pura: no llama a EMAPA ni al LLM. Devuelve la
    estructura tabular que el frontend convierte en .docx. 404 si no hay informe
    en curso para el reclamo.
    """
    informe = informe_store.obtener(codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {codreclamo}.",
        )
    data = construir_sustentacion(informe)
    return SustentacionResponse(codreclamo=codreclamo, **asdict(data))


@router.delete("/{codreclamo}", response_model=FinalizarAtencionResponse)
async def finalizar_atencion(codreclamo: str) -> FinalizarAtencionResponse:
    """
    Cierra la atención de un reclamo: elimina su informe y el token EMAPA
    asociado de la memoria del servidor. Se llama al terminar el flujo
    completo (tras guardar la resolución), para no acumular en memoria
    informes de reclamos ya resueltos indefinidamente.
    """
    eliminado = informe_store.eliminar(codreclamo)
    logger.info("[API DELETE /reclamos/%s] eliminado=%s", codreclamo, eliminado)
    return FinalizarAtencionResponse(codreclamo=codreclamo, eliminado=eliminado)



#Mapa de los medios para el flujo completo de informe de atencion
_MEDIOS_ANALIZABLES: list[tuple[str, str]] = [
    ("tarjeta_lectura", "Tarjeta de Lecturas"),
    ("record_facturacion", "Record de Facturación"),
    ("corte_reapertura", "Cortes y Reaperturas"),
    ("saldo_detalle", "Saldo Detalle"),
    ("inspeccion_externa", "Inspección Externa"),
    ("inspeccion_interna", "Inspección Interna"),
]

from app.src.infrastructure.api_rest.deps import usar_token_emapa, requerir_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService

@router.post("/informe-atencion", response_model=InformeAutomaticoResponse, tags=["automatizacion"])
async def generar_informe_atencion(
    request: InformeAutomaticoRequest,
    token: str = Depends(requerir_token_emapa),
    llm_router: LlmRouterService = Depends(get_llm_router),
) -> InformeAutomaticoResponse:
    """
    Orquesta el flujo COMPLETO del informe de atención en una sola llamada,
    para automatización (nadie mirando la pantalla). Recibe los mismos
    identificadores que GET /reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}
    y hace todo el proceso puertas adentro:

    1. Busca el reclamo en EMAPA y crea los metadatos del informe.
    2. Genera los objetivos de investigación (a partir del motivo).
    3. Analiza los 6 medios probatorios directamente, sin verificar
       disponibilidad antes: si un medio no tiene datos o falla (p.ej. sin
       inspección vinculada), se omite y se sigue con los demás.
    4. Concluye el informe (fundamentación normativa + veredicto).

    Devuelve los resúmenes y la conclusión ya combinados en un solo texto.
    """
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info(
        "[API /reclamos/informe-atencion] codsede=%s | codsuc=%s | codcliente=%s | codreclamo=%s",
        request.codsede, request.codsuc, request.codcliente, request.codreclamo,
    )

    # --- 1. Búsqueda + creación de metadatos --------------------------------
    informe = await buscar_y_crear_informe_o_lanzar(
        request.codsede, request.codsuc, request.codreclamo, request.codcliente,
        token, request.sesion_id, EmapaHttpAdapter(),
    )
    clasificacion = informe.clasificacion or ""

    # --- 2. Objetivos de investigación --------------------------------------
    await generar_objetivos(ObjetivosRequest(codreclamo=request.codreclamo, modelo=request.modelo), llm_router)

    # --- 3. Análisis de los medios probatorios (EN PARALELO) ---------------
    req_medio = BuscarReclamoRequest(
        codsuc=request.codsuc,
        codreclamo=request.codreclamo,
        codcliente=request.codcliente,
        clasificacion=clasificacion,
        meses=request.meses,
        modelo=request.modelo,
    )
    medios_analizados, medios_omitidos = await analizar_medios_en_paralelo(
        req_medio, _MEDIOS_ANALIZABLES, EmapaHttpAdapter(), llm_router
    )

    # --- 4. Conclusión (fundamentación + veredicto) -------------------------
    conclusion_resp = await re_generar_conclusion(
        InformeRequest(
            codreclamo=request.codreclamo,
            clasificacion=clasificacion,
            modelo=request.modelo,
        ),
        llm_router
    )

    informe = informe_store.obtener(request.codreclamo)
    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /reclamos/informe-atencion] COMPLETADO | analizados=%d | omitidos=%d | veredicto=%s | tiempo=%.2fs",
        len(medios_analizados), len(medios_omitidos),
        informe.veredicto if informe else None, tiempo,
    )
    logger.info("=" * 60)

    return InformeAutomaticoResponse(
        codreclamo=request.codreclamo,
        informe_texto=conclusion_resp.informe,
        veredicto=informe.veredicto if informe else None,
        medios_analizados=medios_analizados,
        medios_omitidos=medios_omitidos,
        tiempo=tiempo,
    )


