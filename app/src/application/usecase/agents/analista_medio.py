import json
import time
import logging
from dataclasses import asdict
from langchain_core.messages import HumanMessage, SystemMessage
from app.src.application.adapters.llm import get_llm, log_uso_llm
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.application.services.pre_proces.pre_targeta_lecturas_service import PreTargetaLecturasService
from app.src.application.services.pre_proces.pre_corte_reapertura_service import PreCorteReaperturaService
from app.src.application.services.pre_proces.pre_record_facturacion_service import PreRecordFacturacionService
from app.src.application.services.pre_proces.pre_saldo_detalle_service import PreSaldoDetalleService
from app.src.application.services.pre_proces.problemas_normalizer import (
    extraer_problemas,
    MEDIOS_SOPORTADOS,
)
from app.src.core.model.informe_atencion import BloqueMedio

logger = logging.getLogger("agent.analista_medio")

# Frase predefinida cuando un medio con detección de problemas no halló ninguno.
FRASE_SIN_PROBLEMAS = {
    "inspeccion_externa": "Realizada la inspección externa no se encontró ningún problema.",
    "inspeccion_interna": "Realizada la inspección interna no se encontró ningún problema.",
    "tarjeta_lectura": "Revisada la tarjeta de lecturas no se encontró ninguna anomalía.",
    "corte_reapertura": "Revisados los cortes y reaperturas no se encontró ningún problema.",
    "record_facturacion": "Revisado el record de facturación no se encontró facturación por promedio relevante.",
    "saldo_detalle": "Revisado el saldo-detalle no se encontró cobro indebido, mora ni meses pendientes de pago.",
}


class AnalistaMedioAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)
        self.pre_ext_service = PreInspeccionExternaService()
        self.pre_int_service = PreInspeccionInternaService()
        self.pre_tarj_service = PreTargetaLecturasService()
        self.pre_corte_service = PreCorteReaperturaService()
        self.pre_record_service = PreRecordFacturacionService()
        self.pre_saldo_service = PreSaldoDetalleService()

    def analizar(
        self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str,
        clasificacion: str, meses: int = 12,
        ventana: list[tuple[int, int]] | None = None,
    ) -> tuple[BloqueMedio, list[tuple[int, int]]]:
        """Análisis completo (bloqueante): preprocesa e interpreta en un solo
        paso. Se mantiene para los endpoints no-streaming.

        Devuelve (bloque, ventana). Si el medio es tarjeta_lectura, la ventana
        es la recién calculada; para los demás, se reenvía la recibida."""
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)

        datos, problemas, ventana = self.preprocesar(medio_id, medio_nombre, codsuc, codcliente, meses, ventana)
        resumen = self.interpretar(medio_id, medio_nombre, datos, problemas, clasificacion)

        logger.info("Análisis completado | medio=%s | tiempo=%.2fs", medio_nombre, time.perf_counter() - t_inicio)

        bloque = BloqueMedio(
            medio_id=medio_id,
            medio_nombre=medio_nombre,
            entidad=datos,
            resumen=resumen,
            problemas=problemas,
        )
        return bloque, ventana

    def preprocesar(
        self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str,
        meses: int = 12, ventana: list[tuple[int, int]] | None = None,
    ) -> tuple[dict, list, list[tuple[int, int]]]:
        """Fase 1 (rápida): obtiene la entidad del medio y detecta problemas por
        reglas. Devuelve (datos, problemas, ventana) sin llamar al LLM."""
        t_inicio = time.perf_counter()
        logger.info("Preprocesando medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)

        entidad, ventana = self._dispatch_preprocesamiento(medio_id, codsuc, codcliente, meses, ventana)
        datos = asdict(entidad)

        # Detección de problemas (reglas). [] si el medio aún no la implementa.
        problemas = extraer_problemas(medio_id, entidad)
        logger.info(
            "Preprocesamiento completado | medio=%s | problemas=%d | tiempo=%.2fs",
            medio_nombre, len(problemas), time.perf_counter() - t_inicio,
        )
        return datos, problemas, ventana

    def _resumen_llm(self, medio_nombre: str, datos: dict, clasificacion: str) -> str:
        datos_texto = json.dumps(datos, ensure_ascii=False, indent=2)
        prompt = self._construir_prompt(medio_nombre, datos_texto)
        human = f"Analiza los datos y genera un resumen relevante para un reclamo de: {clasificacion}"

        logger.info(
            "Consultando al modelo | medio=%s | system_chars=%d | human_chars=%d | datos_chars=%d",
            medio_nombre, len(prompt), len(human), len(datos_texto),
        )
        logger.debug("[PROMPT analista_medio][SYSTEM]\n%s", prompt)
        logger.debug("[PROMPT analista_medio][HUMAN]\n%s", human)

        response = self.llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=human)
        ])
        log_uso_llm(logger, f"analista_medio/{medio_nombre}", response)
        return response.content if response.content else ""

    def interpretar(self, medio_id: str, medio_nombre: str, datos: dict, problemas: list, clasificacion: str) -> str:
        """Fase 2 (lenta): genera el resumen en lenguaje natural. Si el medio
        tiene detección de problemas y no halló ninguno, usa una frase
        predefinida y evita la llamada al LLM."""
        if medio_id in MEDIOS_SOPORTADOS and not problemas:
            return FRASE_SIN_PROBLEMAS.get(medio_id, "No se encontró ningún problema.")
        return self._resumen_llm(medio_nombre, datos, clasificacion)
    
    def _dispatch_preprocesamiento(
        self, medio_id: str, codsuc: str, codcliente: str,
        meses: int = 12, ventana: list[tuple[int, int]] | None = None,
    ) -> tuple[object, list[tuple[int, int]]]:
        """Devuelve (entidad_de_dominio, ventana) según el medio.

        Solo tarjeta_lectura calcula una ventana nueva (a partir de `meses`);
        los demás consumen la ventana recibida."""
        ventana = ventana or []
        if medio_id == "inspeccion_externa":
            return self.pre_ext_service.preprocesar_inspeccion_externa(codsuc, codcliente)["inspeccion"], ventana
        elif medio_id == "inspeccion_interna":
            return self.pre_int_service.preprocesar_inspeccion_interna(codsuc, codcliente)["inspeccion"], ventana
        elif medio_id == "tarjeta_lectura":
            resultado = self.pre_tarj_service.preprocesar_targeta_lecturas(codsuc, codcliente, meses)
            return resultado["targeta"], resultado["ventana"]
        elif medio_id == "corte_reapertura":
            return self.pre_corte_service.preprocesar_corte_reapertura(codsuc, codcliente, ventana)["corte"], ventana
        elif medio_id == "record_facturacion":
            return self.pre_record_service.preprocesar_record_facturacion(codsuc, codcliente, ventana)["record"], ventana
        elif medio_id == "saldo_detalle":
            return self.pre_saldo_service.preprocesar_saldo_detalle(codsuc, codcliente, ventana)["saldo"], ventana
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")

    def _construir_prompt(self, medio_nombre: str, datos: str) -> str:
        partes_prompt = [
            "Eres un analista especializado en medios probatorios de EMAPA.",
            "",
            f"Medio probatorio: {medio_nombre}",
            "",
            "Datos obtenidos:",
            datos,
            "",
            "Tu tarea es:",
            "1. Analizar los datos proporcionados",
            "2. Generar un resumen corto (máximo 3-4 oraciones) con los hallazgos relevantes",
            "3. Orientado a la clasificacion del reclamo {clasificacion}",
            "Responde ÚNICAMENTE con el resumen, sin introducciones, recomendaciones ni conclusiones.",
            "Sé conciso y enfócate en lo importante para el reclamo.",
        ]
        return "\n".join(partes_prompt)
