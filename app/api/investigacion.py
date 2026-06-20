import uuid
import logging

from fastapi import APIRouter
from app.tools.emapa_api import (
    buscar_reclamo_emapa,
    obtener_saldo_actual,
    obtener_tarjeta_lectura,
    obtener_record_facturacion,
    obtener_corte_reapertura,
    obtener_inspeccion_externa,
    obtener_inspeccion_interna,
)
from app.schemas.investigacion import (
    InvestigacionRequest,
    ResultadoInvestigacionCompleto,
    PlanificarInvestigacionRequest,
    PlanificarInvestigacionResponse,
    EjecutarInvestigacionRequest,
    ResultadoInvestigacion,
)
from app.orchestrator.workflow import ReclamoWorkflow

router = APIRouter(prefix="/investigacion", tags=["investigacion"])
logger = logging.getLogger("api.investigacion")


@router.post("/iniciar", response_model=ResultadoInvestigacionCompleto)
async def iniciar_investigacion(request: InvestigacionRequest) -> ResultadoInvestigacionCompleto:
    contexto_emapa = {}
    advertencias = []

    if request.codsede and request.codsuc and request.codreclamo and request.codcliente:
        try:
            contexto_emapa["reclamo"] = buscar_reclamo_emapa(
                request.codsede,
                request.codsuc,
                request.codreclamo,
                request.codcliente,
            )
        except Exception as exc:
            logger.warning("No se pudo obtener detalle de reclamo EMAPA: %s", exc)
            advertencias.append("No se pudo obtener detalle de reclamo EMAPA.")

    if request.codsuc and request.codcliente:
        consultas = {
            "saldo_actual": lambda: obtener_saldo_actual(request.codsuc, request.codcliente),
            "tarjeta_lectura": lambda: obtener_tarjeta_lectura(request.codsuc, request.codcliente),
            "corte_reapertura": lambda: obtener_corte_reapertura(request.codsuc, request.codcliente),
            "inspeccion_externa": lambda: obtener_inspeccion_externa(request.codsuc, request.codcliente),
            "inspeccion_interna": lambda: obtener_inspeccion_interna(request.codsuc, request.codcliente),
        }

        for clave, consulta in consultas.items():
            try:
                contexto_emapa[clave] = consulta()
            except Exception as exc:
                logger.warning("No se pudo obtener %s de EMAPA: %s", clave, exc)
                advertencias.append(f"No se pudo obtener {clave} de EMAPA.")

    if request.codsuc and request.codcliente and request.anio:
        try:
            contexto_emapa["record_facturacion"] = obtener_record_facturacion(
                request.codsuc,
                request.codcliente,
                request.anio,
            )
        except Exception as exc:
            logger.warning("No se pudo obtener record_facturacion de EMAPA: %s", exc)
            advertencias.append("No se pudo obtener record_facturacion de EMAPA.")

    workflow = ReclamoWorkflow()
    resultado = workflow.run(
        detalle=request.detalle_reclamo,
        contexto_emapa=contexto_emapa,
    )

    analisis = resultado.get("analisis", {})
    dictamen = resultado.get("dictamen", {})
    reclamo_id = request.codreclamo or f"REC-{uuid.uuid4().hex[:8].upper()}"

    acciones = list(dictamen.get("acciones", [])) if isinstance(dictamen, dict) else []
    acciones.extend(advertencias)

    return ResultadoInvestigacionCompleto(
        reclamo_id=reclamo_id,
        suministro_id=request.suministro_id,
        clasificacion=f"{analisis.get('tipo', 'otro')} / {analisis.get('servicio', 'general')}",
        descripcion_plan="Flujo simplificado con análisis, recuperación normativa y dictamen local.",
        tareas=[],
        resultados_tareas=[],
        explicacion_unificada=dictamen.get("fundamento", "Sin sustento generado."),
        procede="si" if dictamen.get("procede", False) else "no",
        acciones=acciones,
    )


@router.post("/planificar", response_model=PlanificarInvestigacionResponse)
def planificar(request: PlanificarInvestigacionRequest) -> PlanificarInvestigacionResponse:
    return PlanificarInvestigacionResponse(
        reclamo_id=request.reclamo_id,
        clasificacion=request.clasificacion,
        descripcion_planificacion="Planificador heredado removido en favor de workflow local.",
        tareas=[],
    )


@router.post("/ejecutar", response_model=ResultadoInvestigacion)
async def ejecutar(request: EjecutarInvestigacionRequest) -> ResultadoInvestigacion:
    return ResultadoInvestigacion(
        reclamo_id=request.reclamo_id,
        clasificacion=request.clasificacion,
        descripcion_planificacion=request.descripcion_planificacion,
        resultados_tareas=[],
        explicacion_unificada="Ejecutor heredado removido en favor de workflow local.",
    )
