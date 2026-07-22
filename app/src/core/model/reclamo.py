from dataclasses import dataclass


@dataclass
class Reclamo:
    """Datos del reclamo tal como los reporta EMAPA (subconjunto relevante
    para la investigación). Se construye una sola vez, al buscar el reclamo,
    y queda colgado del InformeAtencion para que el resto de pasos lo lean
    desde ahí en vez de volver a tocar el JSON crudo de EMAPA."""
    codcliente: str | None = None
    reclamante: str | None = None
    propietario: str | None = None
    dni: str | None = None                     # dniCliente / nrodocident (DNI/CE del titular)
    tipo_reclamo: str | None = None            # descTipoReclamo
    clasificacion_reclamo: str | None = None   # desCodReclamo
    motivo_reclamo: str | None = None          # motivo
    meses_reclamados: str | None = None        # mesanio
    fecha_recepcion: str | None = None         # fecharec
    estado_reclamo: str | None = None          # descEstadoRec