"""Indexado GENÉRICO de un PDF de reglamento (un punto por artículo), usado por la
carga desde la UI (`POST /normativa/documentos/pdf`, estructura 'generica') para
normas distintas de las dos de la búsqueda escalonada.

Las dos colecciones de Yumi (`sunass_reclamos` y `sunass_reglamento`) NO se indexan con
este módulo (rompe ligaturas, pierde los preámbulos de los artículos y no separa los
numerales): usar `index_reclamos` e `index_calidad`. Por eso este módulo ya no se
ejecuta como script: reindexaría `sunass_reglamento` con el troceo genérico.
"""

import os
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
    calcular_point_id
)

logger = logging.getLogger(__name__)


def extract_articles(pdf_path, is_el_peruano=True):
    """PDF -> bloques ordenados -> articulos estructurados y limpios."""

    blocks = extract_document_structure(pdf_path, is_el_peruano=is_el_peruano)

    articles = parse_document(blocks)

    articles = [
        clean_article(article)
        for article in articles
    ]

    return articles


def build_index(pdf_path, store: PuertoBaseVectorial, coleccion="sunass_reglamento", norma="Reglamento Calidad Servicios Saneamiento", is_el_peruano=True, modificado_por=None, vigencia_desde=None, recrear=False):
    articles = extract_articles(pdf_path, is_el_peruano=is_el_peruano)

    embedder = EmbeddingService()

    qdrant = store

    # Reindexado limpio: se borra la colección para no dejar duplicados de una
    # indexación previa (p.ej. con IDs distintos).
    if recrear:
        qdrant.delete_collection(collection_name=coleccion)

    qdrant.create_collection(
        collection_name=coleccion,
        dimension=embedder.dimension
    )

    points = []

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

        # Un punto por artículo completo (encabezado + cuerpo). El ID
        # determinista (numeral=None) hace que reindexar o editar el artículo lo
        # sobreescriba en vez de duplicarlo.
        article_text = (
            article["articulo"] + "\n" + article["texto"]
        ).strip()

        embedding = embedder.encode_document(article_text)

        points.append(
            {
                "id": calcular_point_id(article_number, None),
                "vector": embedding,
                "payload": {
                    "norma": norma,
                    "source": os.path.basename(pdf_path),
                    "titulo": article["titulo"],
                    "capitulo": article["capitulo"],
                    "subcapitulo": article["subcapitulo"],
                    "article": article_number,
                    "numeral": None,
                    "text": article_text,
                    "estado": "vigente",
                    "modificado_por": modificado_por,
                    "vigencia_desde": vigencia_desde,
                }
            }
        )

    batch_size = 100

    for i in range(
        0,
        len(points),
        batch_size
    ):

        qdrant.upsert(
            collection_name=coleccion,
            points=points[i:i + batch_size]
        )

    logger.info(
        "Chunks indexados: %d",
        len(points)
    )