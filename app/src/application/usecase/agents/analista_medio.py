import json
import time
import logging
from dataclasses import asdict
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.application.services.pre_proces.pre_targeta_lecturas_service import PreTargetaLecturasService
from app.src.application.services.pre_proces.pre_corte_reapertura_service import PreCorteReaperturaService
from app.src.application.services.pre_proces.pre_record_facturacion_service import PreRecordFacturacionService
from app.src.application.services.pre_proces.pre_saldo_detalle_service import PreSaldoDetalleService
from app.src.application.services.pre_proces.problemas_normalizer import extraer_problemas
from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.core.model.informe_atencion import BloqueMedio

logger = logging.getLogger("agent.analista_medio")

# Campos de cabecera del suministro que existen SOLO para el informe de
# sustentación (dirección, titular, ficha del medidor…).
CAMPOS_SOLO_DOCUMENTO = frozenset({
    "propietario", "direccion", "categoria", "diametro", "marca_medidor",
    "tipo_medidor", "nro_medidor", "fecha_instalacion_medidor",
    "fecha_instalacion_conexion", "fecha_verificacion", "tipo_verificacion",
})

# Regla de cierre común a todos los resúmenes: concisión, sin editorializar
# («lo que...»), sin repetir, y solo prosa narrativa.
_CIERRE = (
    "Sé conciso (2-4 oraciones); NO repitas un mismo dato ni agregues cláusulas "
    "interpretativas que empiecen con «lo que...» (p.ej. «lo que "
    "sugiere/impidió/podría...»): describe solo lo observado. Responde ÚNICAMENTE "
    "con el párrafo, sin encabezados, listas ni conclusiones."
)
_REGLA_SOLO_DATOS = (
    "REGLA ESTRICTA: usa ÚNICAMENTE los valores presentes en 'Datos obtenidos'. "
    "NO inventes ni completes datos que no aparezcan. Si un campo está vacío o no "
    "existe, no lo menciones."
)

# Instrucciones de redacción del resumen, ESPECIALIZADAS por medio probatorio.
# Cada medio tiene su propio prompt para extraer lo relevante de sus datos; el
# fallback (_INSTRUCCIONES_DEFAULT) cubre cualquier medio sin entrada propia.
INSTRUCCIONES_POR_MEDIO: dict[str, list[str]] = {
    "inspeccion_externa": [
        "Tu tarea es redactar UN SOLO párrafo en prosa narrando lo observado "
        "durante la inspección EXTERNA, con el tono de un inspector de campo.",
        "",
        _REGLA_SOLO_DATOS,
        "",
        "Estructura sugerida, solo con los campos disponibles:",
        "- Empieza con la fecha (fechainspeccion) y quién la realizó "
        "(nomresponsable): 'Con fecha [fechainspeccion], el señor(a) "
        "[nomresponsable] realizó la inspección externa al predio…'.",
        "- Estado de funcionamiento del medidor (funcionamed) y si se pudo tomar "
        "lectura.",
        "- Fugas: si se detectaron (fugas) y de qué tipo (tipofugas).",
        "- Estado de la caja (estadocaja) y de la conexión (estconexion).",
        "- Condiciones atípicas (atipico) y observaciones (observacionmed, "
        "observacionsum) si las hay.",
        _CIERRE,
    ],
    "inspeccion_interna": [
        "Tu tarea es redactar UN SOLO párrafo en prosa narrando lo observado "
        "durante la inspección INTERNA, con el tono de un inspector de campo.",
        "",
        _REGLA_SOLO_DATOS,
        "",
        "Estructura sugerida, solo con los campos disponibles:",
        "- Empieza con la fecha (fechainspeccion): 'En la inspección interna "
        "realizada con fecha [fechainspeccion]…'.",
        "- Detalla los puntos de agua sumando las cantidades de cada aparato en "
        "'puntos_agua' (inodoro, lavado, ducha, urinario, bidet, grifo, cisterna, "
        "tanque, piscina), SOLO los que tengan cantidad mayor a cero, con el "
        "formato 'cuenta con X inodoros, Y duchas, Z grifos…'.",
        "- Estado del abastecimiento (estadoabas) y categoría del predio (catetar) "
        "si aporta.",
        "- Fugas o consumos atípicos (atipico) y observaciones (obsinsinteriores, "
        "observaciones, obsperrepins) si las hay.",
        _CIERRE,
    ],
    "tarjeta_lectura": [
        "Tu tarea es redactar UN SOLO párrafo en prosa que resuma los hallazgos de "
        "la tarjeta de lecturas RELEVANTES para la facturación del reclamo.",
        "",
        _REGLA_SOLO_DATOS,
        "",
        "Menciona, si están presentes:",
        "- Consumos atípicos o excesivos y en qué meses (errorConsumo).",
        "- Si un consumo elevado retornó al promedio en un mes posterior (fuga no "
        "visible ya reparada), CON las cifras (fugaReparada).",
        "- Errores de lectura o de registro del medidor (errorLecturas, errorServicio).",
        "NO menciones metadatos ni totales de registros.",
        _CIERRE,
    ],
    "record_facturacion": [
        "Tu tarea es redactar UN SOLO párrafo en prosa sobre CÓMO se facturó al "
        "usuario en la ventana del reclamo (por lectura o por promedio).",
        "",
        _REGLA_SOLO_DATOS,
        "",
        "SIEMPRE, si está presente, empieza afirmando la categoría tarifaria "
        "(categoria) con el formato 'La facturación emitida al usuario "
        "corresponde a una categoría [categoria en minúscula].'.",
        "Luego, si están presentes:",
        "- Meses facturados por promedio en vez de por lectura (mesesPromediados).",
        "- Rachas de facturación por promedio consecutivas (rachaPromediados).",
        "Si toda la facturación fue por diferencia de lecturas, dilo brevemente.",
        _CIERRE,
    ],
    "corte_reapertura": [
        "Tu tarea es redactar UN SOLO párrafo en prosa sobre los cortes, "
        "reaperturas y prórrogas del servicio RELEVANTES para el reclamo.",
        "",
        _REGLA_SOLO_DATOS,
        "NO menciones metadatos internos como el total de registros originales "
        "(p.ej. 'totalRegistrosOriginales') ni conteos técnicos.",
        "",
        "Menciona, si están presentes:",
        "- Cortes por deuda y sus meses (cortes, mesesCortados).",
        "- Reaperturas y prórrogas relevantes (reaperturas, prorrogas).",
        "- Reclamos previos del suministro (reclamosPrevios).",
        _CIERRE,
    ],
    "saldo_detalle": [
        "Tu tarea es redactar UN SOLO párrafo en prosa sobre los pagos del "
        "suministro RELEVANTES para el reclamo.",
        "",
        _REGLA_SOLO_DATOS,
        "",
        "Menciona, si están presentes:",
        "- Cobros indebidos por servicio no prestado (cobroIndebido).",
        "- Cobros de mora o recargos (mora).",
        "- Meses pendientes de pago (mesesNoPagados).",
        _CIERRE,
    ],
}

class AnalistaMedioAgent:
    def __init__(self, emapa_api: PuertoEmapaAPI, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        self.pre_ext_service = PreInspeccionExternaService(emapa_api)
        self.pre_int_service = PreInspeccionInternaService(emapa_api)
        self.pre_tarj_service = PreTargetaLecturasService(emapa_api)
        self.pre_corte_service = PreCorteReaperturaService(emapa_api)
        self.pre_record_service = PreRecordFacturacionService(emapa_api)
        self.pre_saldo_service = PreSaldoDetalleService(emapa_api)

    def analizar(
        self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str,
        clasificacion: str, meses: int = 12,
        fecha_ref: str | None = None,
        enfoque: str | None = None,
        codinspeccion: str | None = None,
    ) -> tuple[BloqueMedio, list[tuple[int, int]]]:
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)
        datos, problemas, ventana = self.preprocesar(
            medio_id, medio_nombre, codsuc, codcliente, meses, fecha_ref, codinspeccion,
        )
        resumen = self.interpretar(medio_id, medio_nombre, datos, problemas, clasificacion, enfoque)
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
        meses: int = 12, fecha_ref: str | None = None,
        codinspeccion: str | None = None,
    ) -> tuple[dict, list, list[tuple[int, int]]]:
        """Obtiene la entidad del medio y detecta problemas por reglas. Cada
        medio calcula su propia ventana calendario a partir de (meses, fecha_ref)
        — no depende de que otro medio la haya calculado antes (ver
        ventana_utils.py). `codinspeccion` solo aplica a inspeccion_interna/
        externa (ver _dispatch_preprocesamiento). Devuelve (datos, problemas, ventana)."""
        t_inicio = time.perf_counter()
        logger.info("Preprocesando medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)
        entidad, ventana = self._dispatch_preprocesamiento(
            medio_id, codsuc, codcliente, meses, fecha_ref, codinspeccion,
        )
        datos = asdict(entidad)
        problemas = extraer_problemas(medio_id, entidad)
        logger.info(
            "Preprocesamiento completado | medio=%s | problemas=%d | tiempo=%.2fs",
            medio_nombre, len(problemas), time.perf_counter() - t_inicio,
        )
        return datos, problemas, ventana

    def _resumen_llm(self, medio_id: str, medio_nombre: str, datos: dict, clasificacion: str,
                     enfoque: str | None = None) -> str:
        omitir = CAMPOS_SOLO_DOCUMENTO | {"registros"}
        datos_para_prompt = {k: v for k, v in datos.items() if k not in omitir}
        datos_texto = json.dumps(datos_para_prompt, ensure_ascii=False, indent=2)
        prompt = self._construir_prompt(medio_id, medio_nombre, datos_texto)
        human = f"Analiza los datos y genera un resumen relevante para un reclamo de: {clasificacion}"
        if enfoque:
            human += (
                f"\nLa investigación de este medio busca responder: {enfoque} "
                "Si los datos disponibles lo permiten, resáltalo en el resumen. "
                "Si NO lo permiten, no lo inventes, pero tampoco dejes el resumen "
                "en una disculpa: igual describe brevemente los hechos que SÍ "
                "muestran los datos (como haría el resumen normal sin este enfoque)."
            )

        logger.info(
            "Consultando al modelo | medio=%s | system_chars=%d | human_chars=%d | datos_chars=%d",
            medio_nombre, len(prompt), len(human), len(datos_texto),
        )
        logger.debug("[PROMPT analista_medio][SYSTEM]\n%s", prompt)
        logger.debug("[PROMPT analista_medio][HUMAN]\n%s", human)

        response_text = self.llm_router.generar_texto(
            mensajes=[
                MensajeLLM(rol="system", contenido=prompt),
                MensajeLLM(rol="user", contenido=human)
            ],
            modelo_id=self.model_id
        )
        return response_text

    def interpretar(self, medio_id: str, medio_nombre: str, datos: dict, problemas: list,
                    clasificacion: str, enfoque: str | None = None) -> str:
        """genera el resumen en lenguaje natural. Si el medio no
        halló ningún problema y tiene una frase base (no aplica a inspecciones),
        `enfoque` (opcional) son las preguntas del/los objetivo(s) de
        investigación asignados a este medio; dirigen el énfasis del resumen."""
        if not problemas:
            frase = self._frase_base_sin_problemas(medio_id, datos)
            if frase:
                # No se llama al LLM: se deja constancia de los datos que se le
                # habrían mandado (los mismos que arma _resumen_llm), para poder
                # verificar en el log qué trajo EMAPA aunque no haya prompt real.
                omitir = CAMPOS_SOLO_DOCUMENTO | {"registros"}
                datos_sin_omitir = {k: v for k, v in datos.items() if k not in omitir}
                logger.info(
                    "Sin llamada al LLM (frase base) | medio=%s | frase=%r | datos_que_se_hubieran_mandado=%s",
                    medio_nombre, frase, json.dumps(datos_sin_omitir, ensure_ascii=False),
                )
                return frase
        return self._resumen_llm(medio_id, medio_nombre, datos, clasificacion, enfoque)

    @staticmethod
    def _frase_base_sin_problemas(medio_id: str, datos: dict) -> str | None:
        """Frase predefinida para un medio SIN hallazgos,
        (evita la llamada al LLM cuando no hay nada que interpretar). Cada medio
        arma su propia frase, concatenando datos del reclamo cuando aporta algo
        concreto."""
        if medio_id == "tarjeta_lectura":
            return "Revisada la tarjeta de lecturas no se encontró ninguna anomalía."
        if medio_id == "record_facturacion":
            cat = (datos.get("categoria") or "").strip()
            if cat:
                return (
                    "La facturación emitida al usuario corresponde a una categoría "
                    f"{cat.lower()}."
                )
            return "Revisado el record de facturación del cliente no se encontraron problemas."

        if medio_id == "corte_reapertura":
            return "Revisados los cortes y reaperturas del cliente no se encontrarón problemas."

        if medio_id == "saldo_detalle":
            servicio = (datos.get("tipoServicio") or "").strip()
            if servicio:
                return (
                    f"El cliente no precenta deuda, asimismo cueta con el servicio de {servicio.lower()}."
                )
            return "Asimismo para el cliente no se encontró cobro indebido por servicios no prestados, mora ni meses pendientes de pago."

        return None
    
    def _dispatch_preprocesamiento(
        self, medio_id: str, codsuc: str, codcliente: str,
        meses: int = 12, fecha_ref: str | None = None,
        codinspeccion: str | None = None,
    ) -> tuple[object, list[tuple[int, int]]]:
        """Devuelve (entidad_de_dominio, ventana) según el medio. Los medios de
        serie temporal (tarjeta/record/corte/saldo) calculan su propia ventana
        calendario a partir de (meses, fecha_ref) — ver ventana_utils.py; ninguno
        depende de que otro se haya analizado antes.

        inspeccion_interna/externa NO usan codcliente: usan `codinspeccion` (el
        nroinspeccion vinculado al reclamo), porque el endpoint EMAPA filtra por
        número de inspección, no por cliente (ver reclamos.py `_codigo_inspeccion`
        y el docstring de preprocesar_inspeccion_interna/externa)."""
        if medio_id == "inspeccion_externa":
            return self.pre_ext_service.preprocesar_inspeccion_externa(codsuc, codinspeccion)["inspeccion"], []
        elif medio_id == "inspeccion_interna":
            return self.pre_int_service.preprocesar_inspeccion_interna(codsuc, codinspeccion)["inspeccion"], []
        elif medio_id == "tarjeta_lectura":
            resultado = self.pre_tarj_service.preprocesar_targeta_lecturas(codsuc, codcliente, meses, fecha_ref)
            return resultado["targeta"], resultado["ventana"]
        elif medio_id == "corte_reapertura":
            resultado = self.pre_corte_service.preprocesar_corte_reapertura(codsuc, codcliente, meses, fecha_ref)
            return resultado["corte"], []
        elif medio_id == "record_facturacion":
            resultado = self.pre_record_service.preprocesar_record_facturacion(codsuc, codcliente, meses, fecha_ref)
            return resultado["record"], []
        elif medio_id == "saldo_detalle":
            resultado = self.pre_saldo_service.preprocesar_saldo_detalle(codsuc, codcliente, meses, fecha_ref)
            return resultado["saldo"], []
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")

    def _construir_prompt(self, medio_id: str, medio_nombre: str, datos: str) -> str:
        # Los 6 medios probatorios están fijos por endpoint (no hay uno genérico
        # ni parametrizable por el usuario), así que cada uno DEBE tener su propia
        # entrada en el mapa; si falta, es un error de configuración a corregir,
        # no un caso a tolerar con un prompt genérico.
        instrucciones = INSTRUCCIONES_POR_MEDIO[medio_id]
        partes_prompt = [
            "Eres un analista especializado en medios probatorios de EMAPA.",
            "",
            f"Medio probatorio: {medio_nombre}",
            "",
            "Datos obtenidos:",
            datos,
            "",
            *instrucciones,
        ]
        return "\n".join(partes_prompt)
