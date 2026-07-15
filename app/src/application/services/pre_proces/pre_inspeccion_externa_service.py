import time
import logging
from dataclasses import fields
from app.src.core.model.inspeccion_externa import InspeccionExterna
from app.src.core.model.indicadores.inspeccion_externa_indicadores import INDICADORES_INSPECCION_EXTERNA
from app.src.core.service.tools.emapa_api import obtener_inspeccion_externa

logger = logging.getLogger("services.pre_inspeccion_externa_service")


class PreInspeccionExternaService:

    def preprocesar_inspeccion_externa(self, codsuc: str, codcliente: str) -> dict:
        t1 = time.time()
        json_raw = obtener_inspeccion_externa(codsuc, codcliente)
        logger.info("[PRE_INSPECCION_EXTERNA] Datos obtenidos de EMAPA en %.2f segundos", time.time() - t1)

        inspeccion = self._construir_inspeccion(json_raw)
        observaciones = inspeccion.observaciones()

        logger.info("[PRE_INSPECCION_EXTERNA] Preprocesamiento completo en %.2f segundos", time.time() - t1)
        return {
            "inspeccion": inspeccion,                     # entidad de dominio
            "observaciones": observaciones,
        }

    def _construir_inspeccion(self, json_raw: dict) -> InspeccionExterna:
        """Filtra los campos relevantes (definidos por la entidad), traduce los
        códigos de EMAPA y construye la entidad de dominio."""
        cab = (json_raw or {}).get("data", {}).get("cab", {})
        valores: dict[str, str | None] = {}
        for campo in fields(InspeccionExterna):
            nombre = campo.name
            valor = cab.get(nombre)
            if valor is not None and nombre in INDICADORES_INSPECCION_EXTERNA:
                valor = INDICADORES_INSPECCION_EXTERNA[nombre].get(str(valor), str(valor))
            valores[nombre] = valor
        return InspeccionExterna(**valores)
