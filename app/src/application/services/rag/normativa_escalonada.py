"""Búsqueda normativa ESCALONADA: primero la norma de atención de reclamos y,
solo si no alcanza para argumentar, la norma de calidad.

Este módulo resuelve la parte de recuperación (qué colecciones, en qué orden,
con qué umbral). La decisión de "no alcanza para argumentar" la toma el agente
de fundamentación (el LLM abstiene con aplica=false); aquí solo se ofrece
`buscar(query, fuente)` por nivel y `siguiente(...)` para escalar.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.src.application.services.rag.retriever import Retriever

logger = logging.getLogger("rag.normativa_escalonada")

_TTL_EXISTENCIA_S = 60.0


@dataclass(frozen=True)
class FuenteNormativa:
    coleccion: str
    nombre: str          # nombre completo, para el prompt del LLM
    nombre_corto: str    # para citar ("Art. 15.5 del Reglamento de Reclamos")


CATALOGO: dict[str, FuenteNormativa] = {
    "sunass_reclamos": FuenteNormativa(
        "sunass_reclamos",
        "el TUO del Reglamento General de Reclamos de Usuarios de Servicios de "
        "Saneamiento (RCD 015-2023-SUNASS-CD)",
        "Reglamento de Reclamos",
    ),
    "sunass_reglamento": FuenteNormativa(
        "sunass_reglamento",
        "el TUO del Reglamento de Calidad de la Prestación de los Servicios de "
        "Saneamiento (RCD 058-2023-SUNASS-CD)",
        "Reglamento de Calidad",
    ),
}


def fuentes_configuradas(csv: str) -> list[FuenteNormativa]:
    """'sunass_reclamos,sunass_reglamento' -> fuentes en ese orden. Una colección
    que no está en el catálogo se acepta igual, con su nombre de colección."""
    fuentes = []
    for nombre in (n.strip() for n in csv.split(",")):
        if nombre:
            fuentes.append(CATALOGO.get(nombre) or FuenteNormativa(nombre, f"la normativa '{nombre}'", nombre))
    return fuentes


class BuscadorNormativo:

    def __init__(self, retriever: Retriever, store, fuentes: list[FuenteNormativa],
                 top_k: int, umbral: float):
        self.retriever = retriever
        self.store = store
        self.fuentes = fuentes
        self.top_k = top_k
        self.umbral = umbral
        self._existe: dict[str, tuple[float, bool]] = {}

    def disponible(self, fuente: FuenteNormativa) -> bool:
        """¿Existe la colección en Qdrant? Se cachea poco tiempo para no pagar
        una llamada de red por cada hallazgo, pero detectar una colección recién
        creada sin reiniciar el backend."""
        ahora = time.monotonic()
        previo = self._existe.get(fuente.coleccion)
        if previo and ahora - previo[0] < _TTL_EXISTENCIA_S:
            return previo[1]
        existe = bool(self.store.collection_exists(fuente.coleccion))
        if not existe and (previo is None or previo[1]):
            logger.warning(
                "La colección '%s' no existe en Qdrant: se omite en la búsqueda escalonada "
                "(indexarla con rag.index_reclamos).", fuente.coleccion,
            )
        self._existe[fuente.coleccion] = (ahora, existe)
        return existe

    def buscar(self, query: str, fuente: FuenteNormativa) -> list[dict]:
        """Top-k de UNA fuente por encima del umbral, anotado con la fuente."""
        if not self.disponible(fuente):
            return []
        resultados = self.retriever.retrieve(
            query=query, top_k=self.top_k, collection_name=fuente.coleccion,
        )
        utiles = [r for r in resultados if r.get("score", 0) >= self.umbral]
        logger.info(
            "[%s] %d/%d resultados >= %.2f | mejor=%s",
            fuente.coleccion, len(utiles), len(resultados), self.umbral,
            round(resultados[0]["score"], 4) if resultados else None,
        )
        for r in utiles:
            r["fuente"] = fuente
        return utiles

    def buscar_desde(self, query_por_fuente, nivel: int = 0) -> list[dict]:
        """Recorre las fuentes desde `nivel` y devuelve los resultados de la
        primera que tenga alguno por encima del umbral. `query_por_fuente` es
        una función fuente -> texto de consulta (cada norma habla en su idioma:
        procedimiento en reclamos, facturación en calidad)."""
        for fuente in self.fuentes[nivel:]:
            resultados = self.buscar(query_por_fuente(fuente), fuente)
            if resultados:
                return resultados
        return []

    def nivel_de(self, resultados: list[dict]) -> int:
        """Índice de la fuente a la que pertenecen estos resultados."""
        if resultados and resultados[0].get("fuente") in self.fuentes:
            return self.fuentes.index(resultados[0]["fuente"])
        return 0
