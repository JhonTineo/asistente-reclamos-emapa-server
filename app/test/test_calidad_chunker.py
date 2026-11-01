# -*- coding: utf-8 -*-
"""Chunker del TUO del Reglamento de Calidad (RCD 058-2023-SUNASS-CD).

Cada prueba corresponde a un fallo medido en el índice de desarrollo de calidad
(ver DIAGNOSTICO_RAG.md). Sin Ollama ni Qdrant: solo el PDF del repo.

    python -m pytest app/test/test_calidad_chunker.py -v
"""

import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import pytest

from app.src.application.services.rag.calidad_chunker import (
    MAX_CHARS_CALIDAD,
    TOTAL_ARTICULOS_CALIDAD,
    chunkear_calidad,
    validar_calidad,
)
from app.src.application.services.rag.index_calidad import PDF_CALIDAD_POR_DEFECTO


@pytest.fixture(scope="module")
def chunks():
    return chunkear_calidad(PDF_CALIDAD_POR_DEFECTO)


def _buscar(chunks, article, numeral=None, parte=1):
    return next((c for c in chunks if c.article == article and c.numeral == numeral and c.parte == parte), None)


def test_los_chunks_pasan_la_validacion(chunks):
    assert validar_calidad(chunks) == []


def test_estan_los_137_articulos(chunks):
    # Incluye 126, 127 y 129, que el PDF escribe "Art. 126.-" en vez de "Artículo 126.-".
    assert {int(c.article) for c in chunks if c.article.isdigit()} == set(range(1, TOTAL_ARTICULOS_CALIDAD + 1))


def test_ninguna_ligatura_rota(chunks):
    # Antes: 133 de 266 puntos; la búsqueda por "notificación" daba 0 aciertos.
    assert not any(re.search("[ﬀ-ﬄ]", c.text) for c in chunks)
    texto = " ".join(c.text for c in chunks)
    assert "notificación" in texto and "verificación" in texto and "clasificación" in texto


def test_sin_fragmentos_de_referencias_cruzadas(chunks):
    # Antes: "93.1 y" (6 caracteres) y "93.2, según sea el caso." eran puntos aparte.
    assert min(len(c.text) for c in chunks) >= 100
    assert not any(re.match(r"^\d+\.\d+[,\s]", c.text.split("\n", 1)[1]) and c.tipo_unidad != "numeral"
                   for c in chunks if "\n" in c.text)


def test_el_preambulo_del_art_93_ya_no_se_pierde(chunks):
    pre = _buscar(chunks, "93")
    assert pre is not None
    assert "Promedio Histórico de Consumos, el promedio de las seis (6) últimas diferencias" in pre.text
    assert pre.text.startswith("Artículo 93.- Determinación del Volumen a Facturar por Agua Potable")


def test_numerales_de_93_completos_y_unicos(chunks):
    numerales = sorted(c.numeral for c in chunks if c.article == "93" and c.numeral and c.parte == 1)
    assert numerales == ["93.1", "93.2", "93.3", "93.4", "93.5", "93.6"]
    assert len(_buscar(chunks, "93", "93.1").text) > 100        # antes: "93.1 y"


def test_la_regla_de_fugas_esta_en_92_3(chunks):
    c = _buscar(chunks, "92", "92.3")
    assert "fugas no visibles" in c.text and "promedio histórico de consumos" in c.text
    assert c.capitulo.startswith("CAPÍTULO 5") and c.subcapitulo.startswith("SUBCAPÍTULO 1")


def test_ningun_chunk_pasa_del_maximo(chunks):
    assert max(len(c.text) for c in chunks) <= MAX_CHARS_CALIDAD * 1.3
    # Art. 137 absorbía las disposiciones (7 539 caracteres).
    assert len(_buscar(chunks, "137").text) < 2000


def test_incisos_largos_se_parten_pero_conservan_el_articulo(chunks):
    partes = [c for c in chunks if c.article == "91"]
    assert len(partes) > 1 and all(c.partes == len(partes) for c in partes)
    assert all(c.text.startswith("Artículo 91.-") for c in partes)
    assert any("no se incluye la facturación reclamada" in c.text for c in partes)


def test_parrafo_partido_entre_columnas_se_une(chunks):
    art7 = " ".join(c.text for c in chunks if c.article == "7")
    assert "se instalarán de manera separada" in art7
    assert "preferencia deberán ejecutarse previamente las obras" in art7
    assert not any(c.text.split("\n", 1)[-1].startswith("preferencia deberán") for c in chunks)


def test_titulos_partidos_en_dos_bloques(chunks):
    c = _buscar(chunks, "5")
    assert c.titulo == "TÍTULO SEGUNDO CALIDAD EN EL ACCESO A LOS SERVICIOS DE SANEAMIENTO"
    # La nota "(Texto modificado por…)" pegada al encabezado no forma parte del título.
    assert not any("(Texto" in (c.capitulo or "") + (c.titulo or "") for c in chunks)


def test_disposiciones(chunks):
    assert _buscar(chunks, "Disposición Transitoria y Final Primera") is not None
    assert _buscar(chunks, "Disposición Transitoria y Final Décima Tercera") is not None
    assert _buscar(chunks, "Disposición Complementaria Transitoria Tercera") is not None


def test_ids_unicos(chunks):
    ids = [c.point_id() for c in chunks]
    assert len(set(ids)) == len(ids)
