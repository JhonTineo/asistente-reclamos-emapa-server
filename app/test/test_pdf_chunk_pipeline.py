# -*- coding: utf-8 -*-
"""
Test por pasos del pipeline de extraccion del reglamento (pdf_chunk.py).

Muestra cada etapa:
  1. PDF -> bloques de texto ordenados (extract_document_structure)
  2. bloques -> lista de articulos estructurados y limpios (parse_document + clean_article)
  3. articulo -> chunks que se vectorizaran (split_numerals)

No requiere Ollama ni Qdrant: solo prueba extraccion + chunking.

Ejecutar con el interprete del .venv del proyecto:
    .venv/Scripts/python.exe app/test/test_pdf_chunk_pipeline.py
"""

import os
import re
import sys

# Forzar UTF-8 en la salida para que los acentos se vean bien en Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.insert(0, REPO_ROOT)

from app.src.application.services.rag.pdf_chunk import (
    extract_document_structure,
    parse_document,
    clean_article,
)
from app.src.application.services.chunck.legal_chunker import (
    split_numerals,
)

PDF_PATH = os.path.join(
    REPO_ROOT,
    "app", "src", "storage", "files",
    "RESOLUCIÓN N_º 058-2023-SUNASS-CD-5-36.pdf",
)

ARTICLE_NUMBER_RE = re.compile(r"ART[IÍ]CULO\s+(\d+)", re.IGNORECASE)


def sep(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def paso_1_pdf_a_bloques():
    sep("PASO 1: PDF -> bloques de texto ordenados")

    blocks = extract_document_structure(PDF_PATH)

    print(f"Total de bloques extraidos: {len(blocks)}")
    print("\nPrimeros 15 bloques (en orden de lectura):\n")

    for i, block in enumerate(blocks[:10]):
        texto = block["text"]
        
        print(f"[{i:02d}] (font={block['font_size']:.1f}) {texto}")

    return blocks


def paso_2_bloques_a_articulos(blocks):
    sep("PASO 2: bloques -> lista de articulos estructurados y limpios")

    articles = parse_document(blocks)
    articles = [clean_article(a) for a in articles]

    print(f"Total de articulos detectados: {len(articles)}\n")

    for a in articles[:5]:
        print("-" * 70)
        print(f"  titulo      : {a['titulo']}")
        print(f"  capitulo    : {a['capitulo']}")
        print(f"  subcapitulo : {a['subcapitulo']}")
        print(f"  articulo    : {a['articulo']}")
        cuerpo = a["texto"]
        print(f"  texto       : {cuerpo}")

    if len(articles) > 5:
        print("-" * 70)
        print(f"  ... ({len(articles) - 5} articulos mas)")

    return articles


def paso_3_articulos_a_chunks(articles):
    sep("PASO 3: articulos -> chunks que se vectorizaran")

    total_chunks = 0

    for article in articles:
        match = ARTICLE_NUMBER_RE.search(article["articulo"])
        article_number = match.group(1) if match else None

        article_text = (
            article["articulo"] + "\n" + article["texto"]
        ).strip()

        chunks = split_numerals(article_number, article_text)
        total_chunks += len(chunks)

    print(f"Total de chunks a vectorizar: {total_chunks}\n")

    # Mostrar en detalle los chunks de los primeros 3 articulos
    print("Detalle de chunks (primeros 3 articulos):")

    for article in articles[:30]:
        match = ARTICLE_NUMBER_RE.search(article["articulo"])
        article_number = match.group(1) if match else None

        article_text = (
            article["articulo"] + "\n" + article["texto"]
        ).strip()

        chunks = split_numerals(article_number, article_text)

        print("-" * 70)
        print(f"Articulo {article_number} -> {len(chunks)} chunk(s)")

        for c in chunks:
            texto = c["text"].replace("\n", " ")
            print(f"    [art={c['article']} num={c['numeral']}] {texto}")


def main():
    if not os.path.exists(PDF_PATH):
        print(f"ERROR: no se encontro el PDF en:\n  {PDF_PATH}")
        sys.exit(1)

    print(f"PDF: {PDF_PATH}")

    blocks = paso_1_pdf_a_bloques()
    articles = paso_2_bloques_a_articulos(blocks)
    paso_3_articulos_a_chunks(articles)

    sep("FIN")


if __name__ == "__main__":
    main()
