from fastapi import APIRouter
from app.schemas.investigacion import (
    InvestigacionRequest,
    ResultadoInvestigacionCompleto,
    PlanificarInvestigacionRequest,
    PlanificarInvestigacionResponse,
    EjecutarInvestigacionRequest,
    ResultadoInvestigacion,
)
from app.agent.coordinator import ejecutar_investigacion_completa
from app.agent.planificador import planificar_investigacion
from app.agent.ejecutor import ejecutar_investigacion

router = APIRouter(prefix="/investigacion", tags=["investigacion"])


@router.post("/iniciar", response_model=ResultadoInvestigacionCompleto)
async def iniciar_investigacion(request: InvestigacionRequest) -> ResultadoInvestigacionCompleto:
    """
    Endpoint único que orquesta todo el flujo:
    1. Clasificar reclamo
    2. Planificar investigación
    3. Ejecutar tareas en paralelo
    4. Unificar resultados
    """
    resultado = await ejecutar_investigacion_completa(
        suministro_id=request.suministro_id,
        detalle=request.detalle_reclamo,
        modelo=request.modelo,
    )
    return ResultadoInvestigacionCompleto(**resultado)


@router.post("/planificar", response_model=PlanificarInvestigacionResponse)
def planificar(request: PlanificarInvestigacionRequest) -> PlanificarInvestigacionResponse:
    suministro_id = request.suministro_id or request.reclamo_id
    return planificar_investigacion(
        suministro_id=suministro_id,
        reclamo_id=request.reclamo_id,
        clasificacion=request.clasificacion,
        detalle=request.detalle,
        modelo=request.modelo,
    )


@router.post("/ejecutar", response_model=ResultadoInvestigacion)
async def ejecutar(request: EjecutarInvestigacionRequest) -> ResultadoInvestigacion:
    return await ejecutar_investigacion(
        reclamo_id=request.reclamo_id,
        clasificacion=request.clasificacion,
        detalle=request.detalle,
        descripcion_planificacion=request.descripcion_planificacion,
        tareas=request.tareas,
        modelo=request.modelo,
    )
