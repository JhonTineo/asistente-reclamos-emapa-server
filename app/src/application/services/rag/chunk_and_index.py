"""Indexado de normativa SUNASS (PDF -> chunks por numeral -> Qdrant).

Uso (desde la raíz del repo, con Qdrant y Ollama levantados y el modelo de
embeddings descargado):

    python -m app.src.application.services.rag.chunk_and_index

Reindexa DESDE CERO cada colección del catálogo `NORMAS` (recrear=True), que es
lo necesario al cambiar de modelo de embeddings (cambia la dimensión y los
vectores viejos no son comparables con los nuevos).
"""

import os
import re
import logging

from dotenv import load_dotenv
load_dotenv()

from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.ports.vector_db_port import PuertoBaseVectorial

from app.src.application.services.rag.pdf_chunk import (
    extract_document_structure,
    parse_document,
    clean_article
)

from app.src.application.services.rag.legal_chunker import (
    ARTICLE_NUMBER_RE,
    normalizar_numero_articulo,
    calcular_point_id,
    trocear_articulo,
    texto_para_embedding,
)

logger = logging.getLogger(__name__)


# Catálogo de normativas que se indexan con el script. Cada norma va en su
# propia colección: los endpoints de mantenimiento (/normativa/articulos,
# /normativa/reglamento/reconstruccion) identifican un artículo por
# (colección, número), y ambos reglamentos tienen un "Artículo 14".
NORMAS = [
    {
        "archivo": "RESOLUCIÓN N_º 058-2023-SUNASS-CD-5-36.pdf",
        "coleccion": "sunass_reglamento",
        "norma": "Reglamento de Calidad de la Prestación de los Servicios de Saneamiento",
        "resolucion": "RCD N.º 058-2023-SUNASS-CD",
        "is_el_peruano": True,
    },
    {
        "archivo": "RESOLUCIÓN N 015-2023-SUNASS-CD.pdf",
        "coleccion": "sunass_reclamos",
        "norma": "Reglamento General de Reclamos de Usuarios de Servicios de Saneamiento",
        "resolucion": "RCD N.º 015-2023-SUNASS-CD",
        "is_el_peruano": True,
    },
]

BATCH_EMBEDDING = 16
BATCH_UPSERT = 100


def extract_articles(pdf_path, is_el_peruano=True):
    """PDF -> bloques ordenados -> articulos estructurados y limpios."""

    blocks = extract_document_structure(pdf_path, is_el_peruano=is_el_peruano)

    articles = parse_document(blocks)

    articles = [
        clean_article(article)
        for article in articles
    ]

    return articles


def _titulo_articulo(encabezado: str) -> str:
    """'Artículo 93.- Determinación del Volumen ...' -> 'Determinación del Volumen ...'"""
    partes = re.split(r"\.?\s*-\s*", encabezado, maxsplit=1)
    return partes[1].strip() if len(partes) > 1 else ""


def construir_chunks(pdf_path, norma, resolucion=None, is_el_peruano=True, modificado_por=None, vigencia_desde=None):
    """Extrae los artículos del PDF y los trocea por numeral.

    Devuelve una lista de dicts {id, texto_embedding, payload} lista para
    vectorizar. Separado de `build_index` para poder inspeccionar los chunks
    sin tocar Qdrant ni Ollama.
    """
    articles = extract_articles(pdf_path, is_el_peruano=is_el_peruano)

    chunks = []

    for article in articles:

        match = ARTICLE_NUMBER_RE.search(article["articulo"])

        article_number = (
            normalizar_numero_articulo(match.group(1)) if match else None
        )

        if article_number is None:
            logger.warning(
                "Bloque sin número de artículo, se omite: %.60s",
                article["articulo"]
            )
            continue

        encabezado = article["articulo"].strip()
        texto_articulo = (encabezado + "\n" + article["texto"]).strip()

        for trozo in trocear_articulo(article_number, article["texto"]):

            texto_embedding = texto_para_embedding(
                norma=norma,
                titulo=article["titulo"],
                capitulo=article["capitulo"],
                subcapitulo=article["subcapitulo"],
                encabezado_articulo=encabezado,
                numeral=trozo["numeral"],
                parte=trozo["parte"],
                contexto=trozo["contexto"],
                text=trozo["text"],
            )

            chunks.append({
                # ID determinista: reindexar o editar el numeral lo
                # sobreescribe en vez de duplicarlo.
                "id": calcular_point_id(article_number, trozo["numeral"], trozo["parte"]),
                "texto_embedding": texto_embedding,
                "payload": {
                    "norma": norma,
                    "resolucion": resolucion,
                    "source": os.path.basename(pdf_path),
                    "titulo": article["titulo"],
                    "capitulo": article["capitulo"],
                    "subcapitulo": article["subcapitulo"],
                    "article": article_number,
                    "titulo_articulo": _titulo_articulo(encabezado),
                    "numeral": trozo["numeral"],
                    "parte": trozo["parte"],
                    # Texto del chunk (lo que se muestra / pasa al LLM).
                    "text": trozo["text"],
                    # Artículo completo, para cuando el LLM necesite el
                    # contexto entero del artículo (recuperación "small-to-big").
                    "texto_articulo": texto_articulo,
                    "estado": "vigente",
                    "modificado_por": modificado_por,
                    "vigencia_desde": vigencia_desde,
                },
            })

    return chunks


def build_index(pdf_path, store: PuertoBaseVectorial, coleccion="sunass_reglamento", norma="Reglamento de Calidad de la Prestación de los Servicios de Saneamiento", is_el_peruano=True, modificado_por=None, vigencia_desde=None, recrear=False, resolucion=None):

    chunks = construir_chunks(
        pdf_path,
        norma=norma,
        resolucion=resolucion,
        is_el_peruano=is_el_peruano,
        modificado_por=modificado_por,
        vigencia_desde=vigencia_desde,
    )

    embedder = EmbeddingService()

    qdrant = store

    # Reindexado limpio: se borra la colección para no dejar duplicados de una
    # indexación previa ni vectores de otro modelo (otra dimensión).
    if recrear:
        qdrant.delete_collection(collection_name=coleccion)

    qdrant.create_collection(
        collection_name=coleccion,
        dimension=embedder.dimension
    )

    points = []

    for i in range(0, len(chunks), BATCH_EMBEDDING):
        lote = chunks[i:i + BATCH_EMBEDDING]
        vectores = embedder.encode_documents([c["texto_embedding"] for c in lote])
        for chunk, vector in zip(lote, vectores):
            points.append({
                "id": chunk["id"],
                "vector": vector,
                "payload": chunk["payload"],
            })

    for i in range(0, len(points), BATCH_UPSERT):

        qdrant.upsert(
            collection_name=coleccion,
            points=points[i:i + BATCH_UPSERT]
        )

    logger.info(
        "[%s] %s: %d chunks indexados con %s (dim=%d)",
        coleccion, os.path.basename(pdf_path), len(points),
        embedder.model_name, embedder.dimension,
    )

    return len(points)


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    # chunck -> services -> application -> src
    SRC_DIR = os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(__file__)
            )
        )
    )

    FILES_DIR = os.path.join(SRC_DIR, "storage", "files")

    # Punto de composición del script: acá sí se elige el adaptador concreto.
    from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter

    store = QdrantAdapter()

    for item in NORMAS:
        pdf = os.path.join(FILES_DIR, item["archivo"])
        if not os.path.exists(pdf):
            logger.warning("No se encontró %s, se omite", pdf)
            continue
        build_index(
            pdf,
            store,
            coleccion=item["coleccion"],
            norma=item["norma"],
            resolucion=item["resolucion"],
            is_el_peruano=item["is_el_peruano"],
            recrear=True,
        )
