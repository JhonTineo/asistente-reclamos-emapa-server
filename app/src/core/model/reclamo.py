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
    # Código de inspección (nroinspeccion) vinculado a ESTE reclamo, extraído del
    # último item de inspeccion_interna/inspeccion_externa embebidos en el
    # detalle del reclamo. Es la ÚNICA forma confiable de consultar la
    # inspección correcta: el endpoint get-inspeccion-interna/externa NO filtra
    # por cliente, filtra por nroinspeccion (pasarle el código de suministro
    # devolvía la inspección de OTRO cliente por coincidencia numérica). None si
    # el reclamo no tiene una inspección de ese tipo vinculada todavía.
    codinspeccion_interna: str | None = None
    codinspeccion_externa: str | None = None