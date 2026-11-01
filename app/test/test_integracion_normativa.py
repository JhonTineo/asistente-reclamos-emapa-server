# -*- coding: utf-8 -*-
"""Las dos colecciones de Yumi (chunkers propios) frente a las herramientas de
mantenimiento de normativa (normalizador de artículos y reconstrucción).

Sin Ollama ni Qdrant: Qdrant es un doble que sirve los chunks del PDF del repo.

    python -m pytest app/test/test_integracion_normativa.py -v
"""

import asyncio
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import pytest

from app.src.application.services.rag.calidad_chunker import chunkear_calidad
from app.src.application.services.rag.index_calidad import PDF_CALIDAD_POR_DEFECTO
from app.src.application.services.rag.index_reclamos import PDF_RECLAMOS_POR_DEFECTO
from app.src.application.services.rag.legal_chunker import normalizar_numero_articulo
from app.src.application.services.rag.reclamos_chunker import chunkear_reclamos
from app.src.infrastructure.api_rest import normativa_reconstruccion as reconstruccion


@pytest.mark.parametrize("texto, esperado", [
    ("ARTÍCULO 62-A", "62-A"),
    ("62 - a", "62-A"),
    ("Artículo 62", "62"),
    ("Art. 126.-", "126"),
    ("92", "92"),
    # Anexos y disposiciones no son artículos: antes "ANEXO 3" se leía como el artículo 3.
    ("ANEXO 3", "ANEXO 3"),
    ("ANEXO 2", "ANEXO 2"),
    ("Disposición Final Única", "Disposición Final Única"),
    ("Disposición Transitoria y Final Décima Primera", "Disposición Transitoria y Final Décima Primera"),
])
def test_normalizar_numero_articulo(texto, esperado):
    assert normalizar_numero_articulo(texto) == esperado


class QdrantFalso:
    puntos: list = []

    def get_all(self, collection_name=None):
        return QdrantFalso.puntos


def _reconstruir(chunks, source):
    QdrantFalso.puntos = [{"id": c.point_id(), "payload": c.payload(source)} for c in chunks]
    original = reconstruccion.QdrantAdapter
    reconstruccion.QdrantAdapter = QdrantFalso
    try:
        return asyncio.run(reconstruccion.reconstruir_reglamento(coleccion="x"))
    finally:
        reconstruccion.QdrantAdapter = original


def test_la_reconstruccion_no_marca_inconsistencias_en_calidad():
    # Antes: 10 "numeral_duplicado" (partes de un numeral largo) y 4 "chunk_suelto_con_numerales"
    # (el preámbulo de un artículo con numerales, p. ej. el Art. 93).
    r = _reconstruir(chunkear_calidad(PDF_CALIDAD_POR_DEFECTO), "calidad.pdf")
    assert r.inconsistencias == []
    assert r.total_numerales_activos == 276


def test_la_reconstruccion_no_marca_inconsistencias_en_reclamos():
    # Antes: 14 "numeral_no_coincide" (los anexos se leían como artículos 2 y 3).
    r = _reconstruir(chunkear_reclamos(PDF_RECLAMOS_POR_DEFECTO), "reclamos.pdf")
    assert r.inconsistencias == []
    assert {a.article for a in r.articulos} >= {"ANEXO 2", "ANEXO 3", "3"}
    assert r.total_numerales_activos == 98
