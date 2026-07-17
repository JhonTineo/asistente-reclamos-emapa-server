import logging
import time

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.src.application.usecase.agents.analizador import AnalizadorAgent
from app.src.application.usecase.agents.clasificador_rapido import clasificar_rapido
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoResponse, InformeMetadata, ReclamoSchema,
)
from app.src.application.adapters.emapa_api import buscar_reclamo_emapa
from app.src.application.adapters.http import EmapaSinDatosError
from app.src.application.services.informe.informe_store import informe_store
from app.src.core.model.reclamo import Reclamo
from app.src.infrastructure.api_rest.deps import usar_token_emapa, requerir_token_emapa

logger = logging.getLogger("api.clasificador")

router = APIRouter(prefix="/reclamos", tags=["reclamos"], dependencies=[Depends(usar_token_emapa)])


class ClasificarResponse(BaseModel):
    reclamo_id: str
    suministro_id: str
    clasificacion: str
    descripcion: str | None
    score: float


class ClasificarLLMRequest(BaseModel):
    detalle: str


class ClasificarRapidoRequest(BaseModel):
    motivo: str
    desc_tipo_reclamo: str | None = None
    # Si el reclamo ya fue clasificado por el personal, se respeta y no se
    # vuelve a clasificar (caso: reclamos presenciales ya tipificados).
    des_cod_reclamo: str | None = None


class ClasificarRapidoResponse(BaseModel):
    tipo: str | None
    confianza: str            # "definida" | "alta" | "media" | "baja" | "nula"
    metodo: str               # "sistema" (ya venía) | "reglas"
    score: int = 0
    candidatos: list[dict] = []


class ClasificarLLMResponse(BaseModel):
    success: bool
    codigo: str | None
    nombre: str | None
    seccion: str | None
    error: str | None

def _campo_reclamo(datos: dict | None, campo: str) -> str:
    """Lee un campo del JSON del reclamo (data puede ser dict o lista)."""
    data = datos.get("data") if isinstance(datos, dict) else None
    if isinstance(data, dict):
        return str(data.get(campo) or "").strip()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get(campo) or "").strip()
    return ""


analizador = AnalizadorAgent()

@router.get("/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}", response_model=BuscarReclamoResponse)
async def buscar_reclamo(
    codsede: str,
    codsuc: str,
    codreclamo: str,
    codcliente: str,
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
        datos = buscar_reclamo_emapa(codsede, codsuc, codreclamo, codcliente)
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

    # Motivo (lo que reclama el cliente) y clasificación (desCodReclamo). Se
    # guardan desde ya para que la generación de objetivos los tenga disponibles.
    motivo = _campo_reclamo(datos, "motivo")
    clasificacion = _campo_reclamo(datos, "desCodReclamo")

    # Entidad de dominio Reclamo: datos de EMAPA que el resto de la
    # investigación necesita, ya tipados (se arma una sola vez aquí).
    datos_reclamo = Reclamo(
        codcliente=_campo_reclamo(datos, "codcliente") or None,
        reclamante=_campo_reclamo(datos, "reclamante") or None,
        propietario=_campo_reclamo(datos, "propietario") or None,
        tipo_reclamo=_campo_reclamo(datos, "descTipoReclamo") or None,
        clasificacion_reclamo=clasificacion or None,
        motivo_reclamo=motivo or None,
        meses_reclamados=_campo_reclamo(datos, "mesanio") or None,
        fecha_recepcion=_campo_reclamo(datos, "fecharec") or None,
        estado_reclamo=_campo_reclamo(datos, "descEstadoRec") or None,
    )

    # Se crean los metadatos del informe de atención y quedan en el
    # store, listos para ir llenándose con cada medio analizado.
    informe = informe_store.crear_metadata(
        codreclamo=codreclamo,
        suministro=codcliente,
        datos_reclamo=datos_reclamo,
    )
    # Se guarda el token con el que se buscó el reclamo para reutilizarlo en
    # las consultas de investigación de este mismo reclamo.
    informe_store.guardar_token(codreclamo, token)
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


