import json
import time
import logging
from dataclasses import asdict
from pathlib import Path
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.application.services.pre_proces.pre_targeta_lecturas_service import PreTargetaLecturasService
from app.src.application.services.pre_proces.pre_corte_reapertura_service import PreCorteReaperturaService
from app.src.application.services.pre_proces.pre_record_facturacion_service import PreRecordFacturacionService
from app.src.application.services.pre_proces.pre_saldo_detalle_service import PreSaldoDetalleService
from app.src.application.services.pre_proces.pre_tecnico_operacional import PreTecnicoOperacionalService
from app.src.application.services.pre_proces.problemas_normalizer import extraer_problemas
from app.src.application.services.pre_proces.constataciones import constatar
from app.src.application.services.pre_proces.hechos_tecnico_operacional import (
    extraer_hechos as extraer_hechos_operacional,
)
from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.informe.hechos import asignar_ids_bloque
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion

logger = logging.getLogger("paso.analisis_medio")

# Campos de cabecera del suministro que existen SOLO para el informe de
# sustentación (dirección, titular, ficha del medidor…).
CAMPOS_SOLO_DOCUMENTO = frozenset({
    "propietario", "direccion", "categoria", "diametro", "marca_medidor",
    "tipo_medidor", "nro_medidor", "fecha_instalacion_medidor",
    "fecha_instalacion_conexion", "fecha_verificacion", "tipo_verificacion",
})


class PasoAnalisisMedio:
    def __init__(self, emapa_api: PuertoEmapaAPI, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        self.pre_ext_service = PreInspeccionExternaService(emapa_api)
        self.pre_int_service = PreInspeccionInternaService(emapa_api)
        self.pre_tarj_service = PreTargetaLecturasService(emapa_api)
        self.pre_corte_service = PreCorteReaperturaService(emapa_api)
        self.pre_record_service = PreRecordFacturacionService(emapa_api)
        self.pre_saldo_service = PreSaldoDetalleService(emapa_api)
        self.pre_tecnico_service = PreTecnicoOperacionalService()

    def analizar(
        self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str,
        clasificacion: str, meses: int = 12,
        fecha_ref: str | None = None,
        enfoque: str | None = None,
        codinspeccion: str | None = None,
        ruta_pdf: Path | None = None,
        periodos_reclamados: list[tuple[int, int]] | None = None,
        informe: InformeAtencion | None = None,
    ) -> tuple[BloqueMedio, list[tuple[int, int]]]:
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)
        datos, problemas, ventana = self.preprocesar(
            medio_id, medio_nombre, codsuc, codcliente, meses, fecha_ref, codinspeccion, ruta_pdf,
        )
        constataciones = self.constatar(medio_id, datos, periodos_reclamados)
        resumen = self.interpretar(
            medio_id, medio_nombre, datos, problemas, clasificacion, enfoque, constataciones,
            informe=informe,
        )
        logger.info("Análisis completado | medio=%s | tiempo=%.2fs", medio_nombre, time.perf_counter() - t_inicio)
        bloque = BloqueMedio(
            medio_id=medio_id,
            medio_nombre=medio_nombre,
            entidad=datos,
            resumen=resumen,
            problemas=problemas,
            constataciones=constataciones,
        )
        return bloque, ventana

    def constatar_tecnico_operacional(self, datos: dict, codreclamo: str | None = None) -> list:
        """Hechos del informe técnico operacional: continuidad, interrupciones y
        VPA (ver hechos_tecnico_operacional.py). Usa el LLM solo para extraer,
        con cita literal, lo que el informe dice."""
        return extraer_hechos_operacional(datos, self.llm_router, self.model_id, codreclamo)

    @staticmethod
    def constatar(medio_id: str, datos: dict,
                  periodos_reclamados: list[tuple[int, int]] | None) -> list:
        """Hechos neutros o favorables del medio (ver constataciones.py). Nunca
        interrumpe el análisis: si una regla falla, el medio sigue sin ellos."""
        return constatar(medio_id, datos, periodos_reclamados)

    def preprocesar(
        self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str,
        meses: int = 12, fecha_ref: str | None = None,
        codinspeccion: str | None = None,
        ruta_pdf: Path | None = None,
    ) -> tuple[dict, list, list[tuple[int, int]]]:
        """Obtiene la entidad del medio y detecta problemas por reglas. Cada
        medio calcula su propia ventana calendario a partir de (meses, fecha_ref)
        — no depende de que otro medio la haya calculado antes (ver
        ventana_utils.py). `codinspeccion` solo aplica a inspeccion_interna/
        externa (ver _dispatch_preprocesamiento). Devuelve (datos, problemas, ventana)."""
        t_inicio = time.perf_counter()
        logger.info("Preprocesando medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)
        entidad, ventana = self._dispatch_preprocesamiento(
            medio_id, codsuc, codcliente, meses, fecha_ref, codinspeccion, ruta_pdf,
        )
        datos = asdict(entidad)
        problemas = extraer_problemas(medio_id, entidad)
        logger.info(
            "Preprocesamiento completado | medio=%s | problemas=%d | tiempo=%.2fs",
            medio_nombre, len(problemas), time.perf_counter() - t_inicio,
        )
        return datos, problemas, ventana

    @staticmethod
    def _campos_a_omitir(medio_id: str) -> set[str]:
        """Conserva el detalle mensual de facturación para responder por mes.
        En los demás medios omite 'registros' y los campos de cabecera del suministro
        (CAMPOS_SOLO_DOCUMENTO) SOLO en la tarjeta, porque existen solo ahí y son
        para el informe de sustentación. OJO: record_facturacion tiene su propio
        campo 'categoria' (la categoría tarifaria, que el prompt SÍ necesita); si
        aplicáramos CAMPOS_SOLO_DOCUMENTO a todos los medios, ese 'categoria' se
        omitiría y el LLM lo inventaría."""
        if medio_id == "record_facturacion":
            return set()
        if medio_id == "tarjeta_lectura":
            return CAMPOS_SOLO_DOCUMENTO | {"registros"}
        # url_vista_previa (técnico operacional) es una ruta del frontend, no evidencia.
        return {"registros", "url_vista_previa"}

    def interpretar(self, medio_id: str, medio_nombre: str, datos: dict, problemas: list,
                    clasificacion: str, enfoque: str | None = None,
                    constataciones: list | None = None,
                    informe: InformeAtencion | None = None) -> str:
        """genera el resumen en lenguaje natural. Si el medio no
        halló ningún problema y tiene una frase base (no aplica a inspecciones),
        `enfoque` (opcional) son las preguntas del/los objetivo(s) de
        investigación asignados a este medio; dirigen el énfasis del resumen.

        `informe` (opcional) es la memoria del caso: con él, los hechos reciben
        su ID antes de llegar al modelo y el contexto incluye los datos del
        reclamo."""
        if informe is not None:
            self._asignar_ids_de_hechos(informe, medio_id, medio_nombre, problemas, constataciones)
        if not problemas and not enfoque:
            frase = self._frase_base_sin_problemas(medio_id, datos)
            if frase:
                # No se llama al LLM: se deja constancia de los datos que se le
                # habrían mandado (los mismos que recibiría el modelo), para poder
                # verificar en el log qué trajo EMAPA aunque no haya prompt real.
                datos_sin_omitir = {k: v for k, v in datos.items()
                                    if k not in self._campos_a_omitir(medio_id)}
                # La frase fija se completa con los hechos verificados (p.ej. la
                # lectura del mes reclamado), que son deterministas y no
                # necesitan al LLM para redactarse.
                if constataciones:
                    frase = " ".join([frase, *(c.detalle for c in constataciones)])
                logger.info(
                    "Sin llamada al LLM (frase base) | medio=%s | frase=%r | datos_que_se_hubieran_mandado=%s",
                    medio_nombre, frase, json.dumps(datos_sin_omitir, ensure_ascii=False),
                )
                return frase
        # Todo medio tiene su skill (skills/medios/<medio>.md); si falta, el
        # constructor lo informa como error de configuración.
        return self._resumen_con_contexto(
            medio_id, medio_nombre, datos, problemas, clasificacion, enfoque,
            constataciones, informe,
        )

    @staticmethod
    def _asignar_ids_de_hechos(informe: InformeAtencion, medio_id: str, medio_nombre: str,
                               problemas: list, constataciones: list | None) -> None:
        """Da a cada hecho su ID del registro del caso ANTES de llamar al modelo
        (si no, el resumen no podría verlos). Reutiliza el ID de los hechos que
        se repiten respecto del análisis anterior del mismo medio;
        ``registrar_bloque`` respeta luego estos IDs."""
        anterior = next((b for b in informe.bloques if b.medio_id == medio_id), None)
        provisional = BloqueMedio(
            medio_id=medio_id, medio_nombre=medio_nombre, entidad={}, resumen="",
            problemas=list(problemas), constataciones=list(constataciones or []),
        )
        asignar_ids_bloque(informe, provisional, anterior)

    def _resumen_con_contexto(self, medio_id: str, medio_nombre: str, datos: dict,
                              problemas: list, clasificacion: str, enfoque: str | None,
                              constataciones: list | None,
                              informe: InformeAtencion | None) -> str:
        """Resumen armado por el constructor de contexto: la instrucción sale de
        la skill del medio (sección "Cómo leerlo") y la llamada queda registrada."""
        omitir = self._campos_a_omitir(medio_id)
        contexto = constructor_contexto.construir(
            "resumen_medio", informe,
            medio_id=medio_id,
            medio_nombre=medio_nombre,
            datos={k: v for k, v in datos.items() if k not in omitir},
            hechos=[*problemas, *(constataciones or [])],
            enfoque=enfoque,
            clasificacion=clasificacion,
        )
        return contexto.ejecutar_texto(self.llm_router, self.model_id)

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
            return "Revisados los cortes y reaperturas del cliente no se encontraron problemas."

        if medio_id == "saldo_detalle":
            servicio = (datos.get("tipoServicio") or "").strip()
            if servicio:
                return (
                    f"El cliente no presenta deuda, asimismo cuenta con el servicio de {servicio.lower()}."
                )
            return "Asimismo para el cliente no se encontró cobro indebido por servicios no prestados, mora ni meses pendientes de pago."

        return None
    
    def _dispatch_preprocesamiento(
        self, medio_id: str, codsuc: str, codcliente: str,
        meses: int = 12, fecha_ref: str | None = None,
        codinspeccion: str | None = None,
        ruta_pdf: Path | None = None,
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
        elif medio_id == "tecnico_operacional":
            if ruta_pdf is None:
                raise ValueError("No se cargó un informe técnico operacional para este reclamo.")
            return self.pre_tecnico_service.preprocesar(ruta_pdf, ruta_pdf.name), []
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")
