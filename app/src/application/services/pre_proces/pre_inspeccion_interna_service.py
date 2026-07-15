import time
import logging
from dataclasses import fields
from app.src.core.model.inspeccion_interna import InspeccionInterna, PuntosAgua
from app.src.core.model.indicadores.inspeccion_interna_indicadores import INDICADORES_INSPECCION_INTERNA
from app.src.application.adapters.emapa_api import obtener_inspeccion_interna

logger = logging.getLogger("services.pre_inspeccion_interna_service")


class PreInspeccionInternaService:

    def preprocesar_inspeccion_interna(self, codsuc: str, codcliente: str) -> dict:
        t1 = time.time()
        json_raw = obtener_inspeccion_interna(codsuc, codcliente)
        logger.info("[PRE_INSPECCION_INTERNA] Datos obtenidos de EMAPA en %.2f segundos", time.time() - t1)

        inspeccion = self._construir_inspeccion(json_raw)
        observaciones = inspeccion.observaciones_texto()

        logger.info("[PRE_INSPECCION_INTERNA] Preprocesamiento completo en %.2f segundos", time.time() - t1)
        return {
            "inspeccion": inspeccion,                     # entidad de dominio
            "observaciones": observaciones,
        }

    def _construir_inspeccion(self, json_raw: dict) -> InspeccionInterna:
        """Filtra los campos relevantes (definidos por la entidad), traduce los
        códigos de EMAPA y construye la entidad de dominio."""
        data = (json_raw or {}).get("data", {})
        cab = data.get("cab", {})
        ite = data.get("ite", [])

        valores: dict = {}
        for campo in fields(InspeccionInterna):
            nombre = campo.name
            if nombre == "puntos_agua":
                continue
            valor = cab.get(nombre)
            if valor is not None and nombre in INDICADORES_INSPECCION_INTERNA:
                valor = INDICADORES_INSPECCION_INTERNA[nombre].get(str(valor), str(valor))
            valores[nombre] = valor

        valores["puntos_agua"] = self._extraer_puntos_agua(ite)
        return InspeccionInterna(**valores)

    def _extraer_puntos_agua(self, ite: list) -> list[PuntosAgua]:
        """Convierte los ítems en puntos de agua, descartando los que están en cero."""
        puntos = []
        for item in ite or []:
            p = PuntosAgua(
                inodoro=item.get("inodoro", 0.0) or 0.0,
                lavado=item.get("lavado", 0.0) or 0.0,
                ducha=item.get("ducha", 0.0) or 0.0,
                urinario=item.get("urinario", 0.0) or 0.0,
                bidet=item.get("bidet", 0.0) or 0.0,
                grifo=item.get("grifo", 0.0) or 0.0,
                cisterna=item.get("cisterna", 0.0) or 0.0,
                tanque=item.get("tanque", 0.0) or 0.0,
                piscina=item.get("piscina", 0.0) or 0.0,
            )
            if p.tiene_puntos():
                puntos.append(p)
        return puntos
