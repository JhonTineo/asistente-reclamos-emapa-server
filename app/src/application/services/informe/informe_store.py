"""Almacén en memoria del InformeAtencion, indexado por codreclamo.

El informe se crea al buscar el reclamo (metadatos) y se va llenando con un
BloqueMedio por cada medio probatorio analizado. Es estado de servidor con
vida corta (una investigación en curso); no persiste a disco.
"""

import logging
import threading
from datetime import datetime

from app.src.core.model.informe_atencion import InformeAtencion, BloqueMedio
from app.src.core.model.reclamo import Reclamo

logger = logging.getLogger("services.informe_store")

DESTINATARIO_DEFAULT = "Jefe de la Oficina de Atención al Cliente"
ASUNTO_DEFAULT = "RESULTADOS DE LA EVALUACIÓN DE RECLAMO PRESENTADO"


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
    ) -> InformeAtencion:
        return InformeAtencion(
            numero=f"{codreclamo}-{datetime.now():%Y}-EMAPA-SM",
            fecha=datetime.now(),
            asunto=ASUNTO_DEFAULT,
            reclamo=codreclamo,
            suministro=suministro,
            destinatario=DESTINATARIO_DEFAULT,
            datos_reclamo=datos_reclamo,
        )

    def crear_metadata(
        self,
        codreclamo: str,
        suministro: str,
        datos_reclamo: Reclamo | None = None,
    ) -> InformeAtencion:
        """Crea (o reinicia) el informe con solo sus metadatos."""
        with self._lock:
            informe = self._nuevo_informe(codreclamo, suministro, datos_reclamo)
            self._data[codreclamo] = informe
            logger.info("[INFORME_STORE] Metadatos creados para reclamo %s", codreclamo)
            return informe

    def obtener(self, codreclamo: str) -> InformeAtencion | None:
        return self._data.get(codreclamo)

    def guardar_token(self, codreclamo: str, token: str) -> None:
        """Asocia el token de EMAPA al reclamo (se fija al buscar el reclamo)."""
        with self._lock:
            self._tokens[codreclamo] = token
        logger.info("[INFORME_STORE] Token EMAPA guardado para reclamo %s", codreclamo)

    def obtener_token(self, codreclamo: str) -> str | None:
        """Token con el que se buscó el reclamo, o None si no se guardó."""
        return self._tokens.get(codreclamo)

    def registrar_bloque(
        self,
        codreclamo: str,
        bloque: BloqueMedio,
        suministro: str | None = None,
        clasificacion: str | None = None,
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
