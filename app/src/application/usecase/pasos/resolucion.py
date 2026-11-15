import time
import logging
from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.informe_atencion import InformeAtencion

logger = logging.getLogger("paso.resolucion")

MESES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

# Pie legal de atribuciones: es boilerplate normativo fijo, no lo redacta el
# LLM (evita que invente o altere números de resolución).
CIERRE_LEGAL = (
    "QUE, CON LAS ATRIBUCIONES CONFERIDAS EN LA RESOLUCIÓN DE CONSEJO DIRECTIVO "
    "N.º 066-2006-SUNASS-CD Y RESOLUCIÓN DE CONSEJO DIRECTIVO N.º 088-2007-SUNASS-CD "
    "Y LA RESOLUCIÓN DE CONSEJO DIRECTIVO N.º 011-2007-SUNASS-CD, REGLAMENTO GENERAL "
    "DE RECLAMOS DE USUARIOS DE SERVICIOS DE SANEAMIENTO Y REGLAMENTO DE CALIDAD DE "
    "LA PRESTACIÓN DE SERVICIOS DE SANEAMIENTO RESPECTIVAMENTE; EMAPA SAN MARTÍN "
    "S.A. SE ENCUENTRA FACULTADA PARA RESOLVER."
)


def _fecha_es(fecha) -> str:
    if not fecha:
        return ""
    return f"{fecha.day:02d} DE {MESES_ES[fecha.month - 1].upper()} DEL {fecha.year}"


class PasoResolucion:
    """Redacta los considerandos de la resolución final del reclamo, a partir
    de los datos del reclamo (entidad Reclamo) y la CONCLUSIÓN del informe de
    atención (ambos ya en el store), más la propuesta de conciliación de la
    empresa y la postura del cliente frente a esa propuesta. El veredicto ya
    lo fijó el informe (FUNDADO/INFUNDADO); el LLM solo lo fundamenta, no
    puede cambiarlo. El pie legal de atribuciones se agrega aparte, fijo."""

    def __init__(self, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

    def generar_resolucion(
        self,
        informe: InformeAtencion,
        propuesta_empresa: str,
        propuesta_cliente: str | None = None,
        observaciones: str | None = None,
    ) -> dict:
        t_inicio = time.perf_counter()
        veredicto = (informe.veredicto or "INFUNDADO").strip().upper()

        logger.info("=" * 60)
        logger.info(
            "[RESOLUCION] INICIO | codreclamo=%s | veredicto=%s",
            informe.reclamo, veredicto,
        )

        instrucciones, entrada = self._construir_prompt(
            informe, veredicto, propuesta_empresa, propuesta_cliente, observaciones,
        )
        logger.info("[RESOLUCION] Invocando LLM...")
        t_llm_inicio = time.perf_counter()

        response_text = constructor_contexto.llamar(
            "resolucion", self.llm_router, self.model_id,
            informe=informe, entrada=entrada, instrucciones=instrucciones,
        )
        considerandos = (response_text or "").strip()

        contenido = f"{considerandos}\n{CIERRE_LEGAL}".strip()

        t_llm = time.perf_counter() - t_llm_inicio
        t_duracion = time.perf_counter() - t_inicio

        logger.info("[RESOLUCION] LLM completado (%.2fs) | %d caracteres", t_llm, len(contenido))
        logger.info("[RESOLUCION] COMPLETADO | tipo=%s | tiempo=%.2fs", veredicto, t_duracion)
        logger.info("=" * 60)

        return {
            "resolucion": contenido,
            "tipo": veredicto,
            "tiempo": t_duracion,
        }

    @staticmethod
    def _construir_prompt(
        informe: InformeAtencion,
        veredicto: str,
        propuesta_empresa: str,
        propuesta_cliente: str | None,
        observaciones: str | None,
    ) -> tuple[str, str]:
        """Devuelve (instrucciones del caso, entrada). La estructura fija de los
        considerandos está en skills/pasos/resolucion.md."""
        r = informe.datos_reclamo
        motivo = (r.motivo_reclamo if r else None) or informe.motivo or "no especificado"
        clasificacion = (r.clasificacion_reclamo if r else None) or informe.clasificacion or "no especificada"
        reclamante = (r.reclamante if r else None) or "no especificado"
        meses_reclamados = (r.meses_reclamados if r else None) or "no especificado"
        fecha_recepcion = (r.fecha_recepcion if r else None) or "no especificada"

        cliente_texto = propuesta_cliente or "no registrada"
        observaciones_texto = f"\n- Observaciones: {observaciones}" if observaciones else ""

        instrucciones = (
            f"Veredicto ya determinado (NO modificar): {veredicto}. El último "
            f"considerando debe declarar expresamente que el reclamo SE DECLARA {veredicto}."
        )
        entrada = f"""=== DATOS DEL INFORME DE ATENCIÓN ===
- Número del informe: {informe.numero}
- Fecha del informe: {_fecha_es(informe.fecha)}
- Suministro: {informe.suministro}

=== DATOS DEL RECLAMO ===
- Reclamante: {reclamante}
- Suministro (código cliente): {informe.suministro}
- Motivo del reclamo: {motivo}
- Clasificación: {clasificacion}
- Mes(es) reclamado(s): {meses_reclamados}
- Fecha de recepción del reclamo: {fecha_recepcion}

=== CONCLUSIÓN DE LA INVESTIGACIÓN (Informe N.º {informe.numero}) ===
{informe.conclusion or "(sin conclusión registrada)"}

=== CONCILIACIÓN ===
- Propuesta de la empresa: {propuesta_empresa}
- Postura del cliente frente a la propuesta: {cliente_texto}{observaciones_texto}

Redacta los considerandos de la resolución."""
        return instrucciones, entrada
