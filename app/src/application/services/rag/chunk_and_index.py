import os
import glob
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

        embedding = embedder.encode(article_text)

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

    pdf_path = os.path.join(
        SRC_DIR,
        "storage",
        "files",
        "*.pdf"
    )

    pdfs = glob.glob(
        pdf_path
    )

    if not pdfs:
        logger.warning(
            "No se encontraron PDFs para indexar en %s",
            os.path.join(SRC_DIR, "storage", "files")
        )

    # Punto de composición del script: acá sí se elige el adaptador concreto.
    from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter

    store = QdrantAdapter()
    for pdf in pdfs:
        build_index(pdf, store)