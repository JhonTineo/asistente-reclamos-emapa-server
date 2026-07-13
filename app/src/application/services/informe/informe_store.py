"""Almacén en memoria del InformeAtencion, indexado por codreclamo.

El informe se crea al buscar el reclamo (metadatos) y se va llenando con un
BloqueMedio por cada medio probatorio analizado. Es estado de servidor con
vida corta (una investigación en curso); no persiste a disco.
"""

import logging
import threading
from datetime import datetime

from app.src.core.model.informe_atencion import InformeAtencion, BloqueMedio

logger = logging.getLogger("services.informe_store")

DESTINATARIO_DEFAULT = "Jefe de la Oficina de Atención al Cliente"
ASUNTO_DEFAULT = "RESULTADOS DE LA EVALUACIÓN DE RECLAMO PRESENTADO"


class InformeAtencionStore:

    def __init__(self):
        self._data: dict[str, InformeAtencion] = {}
        self._lock = threading.Lock()

    def _nuevo_informe(
        self,
        codreclamo: str,
        suministro: str,
        clasificacion: str | None,
    ) -> InformeAtencion:
        return InformeAtencion(
            numero=f"{codreclamo}-{datetime.now():%Y}-EMAPA-SM",
            fecha=datetime.now(),
            asunto=ASUNTO_DEFAULT,
            reclamo=codreclamo,
            suministro=suministro,
            destinatario=DESTINATARIO_DEFAULT,
            clasificacion=clasificacion,
        )

    def crear_metadata(
        self,
        codreclamo: str,
        suministro: str,
        clasificacion: str | None = None,
    ) -> InformeAtencion:
        """Crea (o reinicia) el informe con solo sus metadatos."""
        with self._lock:
            informe = self._nuevo_informe(codreclamo, suministro, clasificacion)
            self._data[codreclamo] = informe
            logger.info("[INFORME_STORE] Metadatos creados para reclamo %s", codreclamo)
            return informe

    def obtener(self, codreclamo: str) -> InformeAtencion | None:
        return self._data.get(codreclamo)

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
                informe = self._nuevo_informe(
                    codreclamo, suministro or codreclamo, clasificacion
                )
                self._data[codreclamo] = informe

            if clasificacion and not informe.clasificacion:
                informe.clasificacion = clasificacion

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
