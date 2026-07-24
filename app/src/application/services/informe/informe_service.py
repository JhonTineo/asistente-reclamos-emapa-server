"""Servicio de aplicación para el informe de atención automatizado: la
búsqueda del reclamo + creación de metadatos, propia del flujo de un solo
disparo (POST /reclamos/informe-atencion). Se mantiene separada de la
búsqueda manual (GET /reclamos/reclamo/...) porque acá cualquier fallo debe
cortar todo el proceso (HTTPException) en vez de devolverse como un mensaje
en el cuerpo (200 con `error`), pensado para que el usuario lo vea en pantalla.
"""

import logging

from fastapi import HTTPException

from app.src.application.adapters.emapa_api import buscar_reclamo_emapa
from app.src.application.adapters.http import EmapaSinDatosError
from app.src.application.services.informe.informe_store import informe_store, ReclamoEnAtencionError
from app.src.application.services.investigacion.reclamo_service import campo_reclamo, codigo_inspeccion
from app.src.core.model.reclamo import Reclamo
from app.src.core.model.informe_atencion import InformeAtencion

logger = logging.getLogger("services.informe_service")


async def buscar_y_crear_informe_o_lanzar(
    codsede: str, codsuc: str, codreclamo: str, codcliente: str,
    token: str, sesion_id: str | None,
) -> InformeAtencion:
    """Búsqueda del reclamo + creación de metadatos del informe, propia del
    flujo automatizado: a diferencia de GET /reclamo/... (que devuelve el error
    en el cuerpo con 200, pensado para que el usuario lo vea como mensaje de
    búsqueda), acá cualquier fallo lanza HTTPException y corta el proceso."""
    try:
        datos = buscar_reclamo_emapa(codsede, codsuc, codreclamo, codcliente)
    except EmapaSinDatosError:
        logger.warning(
            "[informe-atencion] Reclamo no encontrado | codsede=%s codsuc=%s codcliente=%s codreclamo=%s",
            codsede, codsuc, codcliente, codreclamo,
        )
        raise HTTPException(
            status_code=404,
            detail="No se encontró el reclamo. Verifica el código de sede, sucursal, cliente y reclamo.",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[informe-atencion] Error EMAPA: %s", str(e))
        raise HTTPException(status_code=502, detail=str(e))

    motivo = campo_reclamo(datos, "motivo")
    clasificacion = campo_reclamo(datos, "desCodReclamo")
    codinspeccion_interna = codigo_inspeccion(datos, "inspeccion_interna")
    codinspeccion_externa = codigo_inspeccion(datos, "inspeccion_externa")
    if not codinspeccion_interna:
        logger.warning("[informe-atencion] Reclamo %s sin inspección interna vinculada", codreclamo)
    if not codinspeccion_externa:
        logger.warning("[informe-atencion] Reclamo %s sin inspección externa vinculada", codreclamo)

    datos_reclamo = Reclamo(
        codcliente=campo_reclamo(datos, "codcliente") or None,
        reclamante=campo_reclamo(datos, "reclamante") or None,
        propietario=campo_reclamo(datos, "propietario") or None,
        dni=campo_reclamo(datos, "dniCliente") or campo_reclamo(datos, "nrodocident") or None,
        tipo_reclamo=campo_reclamo(datos, "descTipoReclamo") or None,
        clasificacion_reclamo=clasificacion or None,
        motivo_reclamo=motivo or None,
        meses_reclamados=campo_reclamo(datos, "mesanio") or None,
        fecha_recepcion=campo_reclamo(datos, "fecharec") or None,
        estado_reclamo=campo_reclamo(datos, "descEstadoRec") or None,
        codinspeccion_interna=codinspeccion_interna,
        codinspeccion_externa=codinspeccion_externa,
    )

    try:
        informe = informe_store.crear_metadata(
            codreclamo=codreclamo,
            suministro=codcliente,
            datos_reclamo=datos_reclamo,
            sesion_id=sesion_id,
        )
    except ReclamoEnAtencionError as e:
        raise HTTPException(status_code=409, detail=str(e))

    informe_store.guardar_token(codreclamo, token)
    return informe
