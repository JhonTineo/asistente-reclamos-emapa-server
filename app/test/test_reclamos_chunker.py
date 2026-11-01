# -*- coding: utf-8 -*-
"""Chunker del TUO del Reglamento de Reclamos (RCD 015-2023-SUNASS-CD).

No requiere Ollama ni Qdrant: solo el PDF del repo.

    python -m pytest app/test/test_reclamos_chunker.py -v
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import pytest

from app.src.application.services.rag.reclamos_chunker import (
    TOTAL_ARTICULOS,
    MAX_CHARS,
    chunkear_reclamos,
    normalizar_texto,
    validar,
)
from app.src.application.services.rag.index_reclamos import PDF_RECLAMOS_POR_DEFECTO


@pytest.fixture(scope="module")
def chunks():
    return chunkear_reclamos(PDF_RECLAMOS_POR_DEFECTO)


def _buscar(chunks, article, numeral=None):
    return next((c for c in chunks if c.article == article and c.numeral == numeral), None)


def test_los_chunks_pasan_la_validacion(chunks):
    assert validar(chunks) == []


def test_estan_los_46_articulos_y_ninguno_sobra(chunks):
    articulos = {int(c.article) for c in chunks if c.article.isdigit()}
    assert articulos == set(range(1, TOTAL_ARTICULOS + 1))


def test_el_indice_y_la_resolucion_no_se_cuelan(chunks):
    # El índice lista "Artículo 14. Inspección" sin guion; la resolución usa "Artículo 1º.-".
    assert not any("Aprobar el Texto Único Ordenado" in c.text for c in chunks)
    assert not any(c.text.count("Artículo") >= 4 and c.tipo_unidad != "anexo" for c in chunks)


def test_ningun_chunk_absorbe_el_resto_del_documento(chunks):
    # Con pdf_chunk.parse_document el Art. 46 salía con ~51 000 caracteres.
    assert max(len(c.text) for c in chunks) <= MAX_CHARS * 1.3
    art46 = _buscar(chunks, "46")
    assert len(art46.text) < 500 and "ANEXO" not in art46.text


def test_numeral_con_su_articulo_y_titulo(chunks):
    c = _buscar(chunks, "15", "15.5")
    assert c.text.startswith("Artículo 15.- Verificación posterior de medidores\n15.5.")
    assert "sobrerregistra" in c.text
    assert c.capitulo == "CAPÍTULO 2: ETAPA DE INVESTIGACIÓN"
    assert c.titulo.startswith("TÍTULO TERCERO")


def test_la_nota_de_origen_es_metadato_no_texto(chunks):
    c = _buscar(chunks, "15", "15.5")
    assert any("061-2018-SUNASS-CD" in o for o in c.origen)
    assert "(Texto" not in c.text


def test_el_preambulo_del_articulo_no_se_pierde(chunks):
    # split_numerals descartaba todo lo anterior al primer numeral.
    c = _buscar(chunks, "5")
    assert c is not None and c.tipo_unidad == "preambulo"
    assert "Formato 1" in c.text


def test_una_referencia_cruzada_no_abre_un_numeral(chunks):
    # 5.2 cita "el artículo 4.b)" y 36.3 cita "el artículo 20.1 de la Ley": no son numerales.
    numerales_5 = sorted(c.numeral for c in chunks if c.article == "5" and c.numeral)
    assert numerales_5 == ["5.1", "5.2", "5.3"]
    numerales_36 = sorted(c.numeral for c in chunks if c.article == "36" and c.numeral)
    assert numerales_36 == ["36.1", "36.2", "36.3", "36.4", "36.5"]


def test_ligaturas_reparadas(chunks):
    assert normalizar_texto("Veriﬁ cación y notiﬁ cación de Nº 088") == "Verificación y notificación de Nº 088"
    assert not any(c for c in chunks if "ﬁ" in c.text or "ﬂ" in c.text)
    assert "Verificación posterior" in _buscar(chunks, "15", "15.1").text


def test_titulo_en_dos_bloques_se_une(chunks):
    c = _buscar(chunks, "3")
    assert c.titulo == "TÍTULO SEGUNDO: SOLICITUD DE ATENCIÓN DE PROBLEMAS OPERACIONALES Y COMERCIALES NO RELATIVOS A LA FACTURACIÓN"


def test_disposiciones_y_anexos(chunks):
    assert _buscar(chunks, "Disposición Transitoria Primera") is not None
    assert _buscar(chunks, "Disposición Final Única") is not None
    assert "24 horas" in _buscar(chunks, "ANEXO 2", "operacionales").text
    consumo = _buscar(chunks, "ANEXO 3", "B.1.1")
    assert "Consumo medido" in consumo.text and "Inspección externa" in consumo.text


def test_los_ids_son_unicos_y_estables(chunks):
    ids = [c.point_id() for c in chunks]
    assert len(set(ids)) == len(ids)
    # Misma fórmula que normativa_articulos._calcular_point_id.
    import uuid
    assert _buscar(chunks, "14", "14.2").point_id() == str(uuid.uuid5(uuid.NAMESPACE_DNS, "14_14.2"))
