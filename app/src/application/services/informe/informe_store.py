"""Almacén en memoria del InformeAtencion, indexado por codreclamo.

El informe se crea al buscar el reclamo (metadatos) y se va llenando con un
BloqueMedio por cada medio probatorio analizado. Es estado de servidor con
vida corta (una investigación en curso); no persiste a disco.
"""

import logging
import threading
import shutil
from dataclasses import asdict
from pathlib import Path
from datetime import datetime

from app.src.core.model.informe_atencion import InformeAtencion, BloqueMedio
from app.src.core.model.reclamo import Reclamo
from app.src.core.model.conciliacion import Conciliacion

logger = logging.getLogger("services.informe_store")

DESTINATARIO_DEFAULT = "Jefe de la Oficina de Atención al Cliente"
ASUNTO_DEFAULT = "RESULTADOS DE LA EVALUACIÓN DE RECLAMO PRESENTADO"


class ReclamoEnAtencionError(Exception):
    """El reclamo ya tiene un informe en curso abierto por otra sesión
    (sesion_id distinto). Se lanza al buscar un reclamo que otra pestaña ya
    está atendiendo, para no pisar su avance."""

    def __init__(self, codreclamo: str):
        self.codreclamo = codreclamo
        super().__init__(
            f"El reclamo {codreclamo} ya se está atendiendo en otra ventana."
        )


class InformeAtencionStore:

    def __init__(self):
        self._data: dict[str, InformeAtencion] = {}
        # Token de EMAPA con el que se buscó cada reclamo. Se guarda al buscar
        # el reclamo y se reutiliza en los demás pasos (investigación) de ese
        # mismo reclamo. Indexado por codreclamo para no mezclar reclamos que
        # se atienden en paralelo.
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()

    def _nuevo_informe(
        self,
        codreclamo: str,
        suministro: str,
        datos_reclamo: Reclamo | None = None,
        creado_por: str | None = None,
    ) -> InformeAtencion:
        return InformeAtencion(
            numero=f"{codreclamo}-{datetime.now():%Y}-EMAPA-SM",
            fecha=datetime.now(),
            asunto=ASUNTO_DEFAULT,
            reclamo=codreclamo,
            suministro=suministro,
            destinatario=DESTINATARIO_DEFAULT,
            datos_reclamo=datos_reclamo,
            creado_por=creado_por,
        )

    def crear_metadata(
        self,
        codreclamo: str,
        suministro: str,
        datos_reclamo: Reclamo | None = None,
        sesion_id: str | None = None,
        creado_por: str | None = None,
    ) -> InformeAtencion:
        """Crea el informe con solo sus metadatos, o si ya existe uno en
        curso para este reclamo:

        - Si lo abrió la MISMA sesión (mismo ``sesion_id``, o la existente
          todavía no tenía dueño registrado), se refresca la metadata sin
          perder el avance ya hecho (bloques, objetivos, conclusión). Esto
          es lo que pasa si el frontend recarga o vuelve a buscar el mismo
          reclamo en la misma pestaña.
        - Si lo abrió OTRA sesión (``sesion_id`` distinto), se rechaza con
          ``ReclamoEnAtencionError`` para no pisar el trabajo en curso de
          esa otra ventana.
        """
        with self._lock:
            existente = self._data.get(codreclamo)
            if existente is not None:
                if existente.sesion_id and sesion_id and existente.sesion_id != sesion_id:
                    raise ReclamoEnAtencionError(codreclamo)
                existente.suministro = suministro
                existente.datos_reclamo = datos_reclamo
                if sesion_id:
                    existente.sesion_id = sesion_id
                logger.info(
                    "[INFORME_STORE] Reclamo %s ya en curso; se refresca metadata "
                    "sin perder avance (bloques=%d)",
                    codreclamo, len(existente.bloques),
                )
                return existente

            informe = self._nuevo_informe(
                codreclamo, suministro, datos_reclamo, creado_por,
            )
            informe.sesion_id = sesion_id
            self._data[codreclamo] = informe
            logger.info("[INFORME_STORE] Metadatos creados para reclamo %s", codreclamo)
            return informe

    def obtener(self, codreclamo: str) -> InformeAtencion | None:
        return self._data.get(codreclamo)

    @staticmethod
    def _invalidar_decision_locked(informe: InformeAtencion, motivo: str) -> None:
        tenia_resultado = bool(
            informe.veredicto or informe.conclusion
            or informe.propuesta_conciliacion or informe.resolucion
        )
        if tenia_resultado:
            informe.historial_decisiones.append({
                "fecha": datetime.now().isoformat(),
                "veredicto": informe.veredicto,
                "conclusion": informe.conclusion,
                "estado_evaluacion": informe.estado_evaluacion,
                "origen_decision": informe.origen_decision,
                "propuesta_conciliacion": (
                    asdict(informe.propuesta_conciliacion)
                    if informe.propuesta_conciliacion else None
                ),
                "resolucion": informe.resolucion,
                "invalidada_por": motivo,
            })
        informe.veredicto = None
        informe.conclusion = None
        informe.propuesta_conciliacion = None
        informe.resolucion = None
        informe.estado_evaluacion = "pendiente"
        informe.motivos_evaluacion = []
        informe.mensaje_evaluacion = (
            "La evidencia cambió; se requiere una nueva evaluación."
            if tenia_resultado else None
        )
        informe.origen_decision = None

    def invalidar_decision(self, codreclamo: str, motivo: str) -> bool:
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            self._invalidar_decision_locked(informe, motivo)
            return True

    def listar_metadatos(self) -> list[dict]:
        """Metadatos mínimos de cada informe vivo en memoria (codreclamo +
        codcliente + sesion_id + veredicto). Sirve para que el frontend
        reconstruya la cola de reclamos desde el SERVIDOR —fuente de verdad
        compartida entre navegadores— y no solo desde su localStorage (que es
        por-navegador). Con codreclamo + codcliente basta para pintar la tarjeta
        de la cola; el detalle se pide al seleccionar."""
        with self._lock:
            return [
                {
                    "codreclamo": codreclamo,
                    "codcliente": (
                        informe.datos_reclamo.codcliente
                        if informe.datos_reclamo else None
                    ),
                    "sesion_id": informe.sesion_id,
                    "creado_por": informe.creado_por,
                    "veredicto": informe.veredicto,
                }
                for codreclamo, informe in self._data.items()
            ]

    def eliminar(self, codreclamo: str) -> bool:
        """Cierra la atención de un reclamo: quita su informe y token de la
        memoria del servidor. Se llama al terminar el flujo completo (tras
        guardar la resolución), para no acumular informes de reclamos ya
        resueltos indefinidamente. Devuelve True si había algo que borrar."""
        with self._lock:
            informe = self._data.pop(codreclamo, None)
            existia = informe is not None
            self._tokens.pop(codreclamo, None)
        documento = informe.documento_tecnico_operacional if informe else None
        ruta = Path(documento["ruta"]) if documento and documento.get("ruta") else None
        if ruta and ruta.parent.exists():
            shutil.rmtree(ruta.parent)
        logger.info("[INFORME_STORE] Reclamo %s eliminado de memoria (existia=%s)", codreclamo, existia)
        return existia

    def guardar_documento_tecnico_operacional(self, codreclamo: str, documento: dict) -> None:
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                raise KeyError(f"No hay un informe en curso para el reclamo {codreclamo}.")
            informe.documento_tecnico_operacional = documento

    def obtener_documento_tecnico_operacional(self, codreclamo: str) -> dict | None:
        informe = self._data.get(codreclamo)
        return informe.documento_tecnico_operacional if informe else None

    def guardar_token(self, codreclamo: str, token: str) -> None:
        """Asocia el token de EMAPA al reclamo (se fija al buscar el reclamo)."""
        with self._lock:
            self._tokens[codreclamo] = token
        logger.info("[INFORME_STORE] Token EMAPA guardado para reclamo %s", codreclamo)

    def obtener_token(self, codreclamo: str) -> str | None:
        """Token con el que se buscó el reclamo, o None si no se guardó."""
        return self._tokens.get(codreclamo)

    def actualizar_resumen(self, codreclamo: str, medio_id: str, resumen: str) -> bool:
        """Edita a mano el resumen (texto narrativo) de un medio ya analizado,
        sin tocar los `problemas` estructurados de ese bloque. Invalida la
        decisión automática vigente y archiva sus documentos derivados.
        Devuelve False si no hay informe o no hay bloque para ese medio."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            bloque = next((b for b in informe.bloques if b.medio_id == medio_id), None)
            if bloque is None:
                return False
            self._invalidar_decision_locked(informe, f"edición del resumen {medio_id}")
            bloque.resumen = resumen
            logger.info(
                "[INFORME_STORE] Resumen editado a mano: reclamo=%s medio=%s",
                codreclamo, medio_id,
            )
            return True

    def actualizar_conclusion(self, codreclamo: str, texto: str) -> bool:
        """Edita a mano el párrafo de conclusión, sin tocar el veredicto ni
        regenerar nada. Devuelve False si no hay informe para ese reclamo."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            informe.conclusion = texto
            logger.info("[INFORME_STORE] Conclusión editada a mano: reclamo=%s", codreclamo)
            return True

    def actualizar_fundamentacion(self, codreclamo: str, texto: str) -> bool:
        """Edita a mano el párrafo de fundamentación normativa, sin re-seleccionar
        problemas ni regenerar nada. Devuelve False si no hay informe."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            self._invalidar_decision_locked(informe, "edición de la fundamentación")
            informe.fundamentacion_normativa = texto
            logger.info("[INFORME_STORE] Fundamentación editada a mano: reclamo=%s", codreclamo)
            return True

    def actualizar_propuesta(self, codreclamo: str, texto: str) -> bool:
        """Edita a mano el texto de la propuesta de conciliación (de la
        empresa). Devuelve False si no hay informe para ese reclamo."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            if informe.propuesta_conciliacion is None:
                informe.propuesta_conciliacion = Conciliacion()
            informe.propuesta_conciliacion.propuesta_empresa = texto
            logger.info("[INFORME_STORE] Propuesta editada a mano: reclamo=%s", codreclamo)
            return True

    def actualizar_conciliacion(
        self,
        codreclamo: str,
        propuesta_reclamante: str | None = None,
        puntos_acuerdo: str | None = None,
        puntos_desacuerdo: str | None = None,
        observaciones: str | None = None,
    ) -> Conciliacion | None:
        """Edita a mano los datos de la conciliación aportados por el
        reclamante/agente (no la propuesta de la empresa, que tiene su propio
        ``actualizar_propuesta``). Solo pisa los campos que vengan no-None.
        Devuelve la entidad actualizada, o None si no hay informe para ese reclamo."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return None
            if informe.propuesta_conciliacion is None:
                informe.propuesta_conciliacion = Conciliacion()
            conciliacion = informe.propuesta_conciliacion
            if propuesta_reclamante is not None:
                conciliacion.propuesta_reclamante = propuesta_reclamante
            if puntos_acuerdo is not None:
                conciliacion.puntos_acuerdo = puntos_acuerdo
            if puntos_desacuerdo is not None:
                conciliacion.puntos_desacuerdo = puntos_desacuerdo
            if observaciones is not None:
                conciliacion.observaciones = observaciones
            logger.info("[INFORME_STORE] Datos de conciliación editados a mano: reclamo=%s", codreclamo)
            return conciliacion

    def actualizar_resolucion(self, codreclamo: str, texto: str) -> bool:
        """Edita a mano el texto de la resolución. Devuelve False si no hay
        informe para ese reclamo."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                return False
            informe.resolucion = texto
            logger.info("[INFORME_STORE] Resolución editada a mano: reclamo=%s", codreclamo)
            return True

    def registrar_bloque(
        self,
        codreclamo: str,
        bloque: BloqueMedio,
        suministro: str | None = None,
        clasificacion: str | None = None,
        preservar_decision: bool = False,
    ) -> InformeAtencion:
        """Agrega el bloque de un medio. Si el informe no existía (p.ej. no se
        pasó por la búsqueda del reclamo), lo crea al vuelo."""
        with self._lock:
            informe = self._data.get(codreclamo)
            if informe is None:
                logger.warning(
                    "[INFORME_STORE] Informe %s inexistente; creando al vuelo",
                    codreclamo,
                )
                datos_reclamo = Reclamo(clasificacion_reclamo=clasificacion) if clasificacion else None
                informe = self._nuevo_informe(codreclamo, suministro or codreclamo, datos_reclamo)
                self._data[codreclamo] = informe

            if not preservar_decision:
                self._invalidar_decision_locked(informe, f"nuevo análisis de {bloque.medio_id}")

            # `clasificacion` es de solo lectura (se deriva de datos_reclamo);
            # si aún no se conocía, se completa aquí sobre la misma entidad.
            if clasificacion and not informe.clasificacion:
                if informe.datos_reclamo is None:
                    informe.datos_reclamo = Reclamo(clasificacion_reclamo=clasificacion)
                else:
                    informe.datos_reclamo.clasificacion_reclamo = clasificacion

            # Reemplaza el bloque del mismo medio si ya se había analizado.
            informe.bloques = [
                b for b in informe.bloques if b.medio_id != bloque.medio_id
            ]
            informe.bloques.append(bloque)
            logger.info(
                "[INFORME_STORE] Bloque '%s' registrado en reclamo %s (total=%d)",
                bloque.medio_id, codreclamo, len(informe.bloques),
            )
            return informe


# Singleton de proceso.
informe_store = InformeAtencionStore()
