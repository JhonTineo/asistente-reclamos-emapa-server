import time
import logging
from langchain_core.messages import SystemMessage
from app.src.application.adapters.llm import get_llm, log_uso_llm
from app.src.core.model.informe_atencion import InformeAtencion

logger = logging.getLogger("agent.resolucion")

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


class ResolucionAgent:
    """Redacta los considerandos de la resolución final del reclamo, a partir
    de los datos del reclamo (entidad Reclamo) y la CONCLUSIÓN del informe de
    atención (ambos ya en el store), más la propuesta de conciliación de la
    empresa y la postura del cliente frente a esa propuesta. El veredicto ya
    lo fijó el informe (FUNDADO/INFUNDADO); el LLM solo lo fundamenta, no
    puede cambiarlo. El pie legal de atribuciones se agrega aparte, fijo."""

    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

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

        prompt = self._construir_prompt(informe, veredicto, propuesta_empresa, propuesta_cliente, observaciones)
        logger.debug("[PROMPT resolucion][SYSTEM]\n%s", prompt)
        logger.info("[RESOLUCION] Invocando LLM...")
        t_llm_inicio = time.perf_counter()

        response = self.llm.invoke([SystemMessage(content=prompt)])
        log_uso_llm(logger, "resolucion", response)
        considerandos = (response.content or "").strip()

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
    ) -> str:
        r = informe.datos_reclamo
        motivo = (r.motivo_reclamo if r else None) or informe.motivo or "no especificado"
        clasificacion = (r.clasificacion_reclamo if r else None) or informe.clasificacion or "no especificada"
        reclamante = (r.reclamante if r else None) or "no especificado"
        meses_reclamados = (r.meses_reclamados if r else None) or "no especificado"
        fecha_recepcion = (r.fecha_recepcion if r else None) or "no especificada"

        cliente_texto = propuesta_cliente or "no registrada"
        observaciones_texto = f"\n- Observaciones: {observaciones}" if observaciones else ""

        return f"""Eres un agente que redacta los CONSIDERANDOS de una RESOLUCIÓN de reclamo
de EMAPA, según el Reglamento General de Reclamos de Usuarios de Servicios de
Saneamiento y el Reglamento de Calidad SUNASS.

IMPORTANTE: el veredicto YA fue determinado por el informe de atención y NO
puedes cambiarlo: {veredicto}. Tu única tarea es redactar los considerandos que
lo fundamentan, con el mismo estilo formal de una resolución administrativa
(párrafos que empiezan con "QUE," o "QUE, SEGÚN..."), EN MAYÚSCULAS donde
corresponda, tal como en el ejemplo de estructura.

ESTRUCTURA A SEGUIR (no repitas literalmente el ejemplo, redacta con los datos
reales de este caso):
1. Un considerando "QUE EL RECURRENTE HA SEGUIDO UN PROCEDIMIENTO ADMINISTRATIVO
   REGULAR PARA QUE SE RECONOZCA SU DERECHO DE RECLAMO POR [tema del reclamo,
   basado en la clasificación/motivo]."
2. Un considerando "QUE, SEGÚN INFORME N.º {informe.numero} DE FECHA
   {_fecha_es(informe.fecha)}, INFORMA EN ATENCIÓN AL RECLAMO PRESENTADO POR EL
   SUMINISTRO N.º {informe.suministro}, SE HA REALIZADO EL PROCEDIMIENTO
   ESTABLECIDO EN LA NORMATIVA, EL MISMO QUE NOS CONLLEVA AL SIGUIENTE
   RESULTADO:" seguido de un resumen técnico de los hallazgos de la
   investigación (usa SOLO la conclusión de la investigación que se te da
   abajo; no inventes cifras, lecturas ni hechos que no estén ahí).
3. Si corresponde, menciona brevemente la conciliación: si el cliente aceptó
   la propuesta de la empresa dilo así; si no la aceptó o no hay registro,
   indica que se resuelve conforme a lo determinado técnicamente en la
   investigación.
4. Cierra el último considerando declarando expresamente que el reclamo SE
   DECLARA {veredicto}.

NO agregues el pie de atribuciones legales (SUNASS 066/088/011): se agrega
aparte, fuera de tu respuesta.
Responde ÚNICAMENTE con los considerandos redactados, sin encabezados, sin
comentarios ni el pie legal.

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

Veredicto ya determinado (NO modificar): {veredicto}

Redacta los considerandos de la resolución."""
