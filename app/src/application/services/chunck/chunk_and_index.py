import os
import re
import uuid
import glob
import logging

from dotenv import load_dotenv
load_dotenv()

from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore

from app.src.application.services.chunck.pdf_chunk import (
    extract_document_structure,
    parse_document,
    clean_article
)

from app.src.application.services.chunck.legal_chunker import (
    split_numerals
)

logger = logging.getLogger(__name__)


ARTICLE_NUMBER_RE = re.compile(
    r"ART[IÍ]CULO\s+(\d+)",
    re.IGNORECASE
)


def extract_articles(pdf_path, is_el_peruano=True):
    """PDF -> bloques ordenados -> articulos estructurados y limpios."""

    blocks = extract_document_structure(pdf_path, is_el_peruano=is_el_peruano)

    articles = parse_document(blocks)

    articles = [
        clean_article(article)
        for article in articles
    ]

    return articles


def build_index(pdf_path, coleccion="sunass_reglamento", norma="Reglamento Calidad Servicios Saneamiento", is_el_peruano=True):
    articles = extract_articles(pdf_path, is_el_peruano=is_el_peruano)

    embedder = EmbeddingService()

    qdrant = QdrantStore()

    qdrant.create_collection(
        collection_name=coleccion,
        dimension=embedder.dimension
    )

    points = []

    for article in articles:

        match = ARTICLE_NUMBER_RE.search(article["articulo"])

        article_number = match.group(1) if match else None

        article_text = (
            article["articulo"] + "\n" + article["texto"]
        ).strip()

        chunks = split_numerals(
            article_number,
            article_text
        )

        for chunk in chunks:

            embedding = embedder.encode(
                chunk["text"],
            )

            # Crear un ID basado en el articulo y numeral para que las actualizaciones sobre el mismo articulo lo sobreescriban
            unique_str = f"{chunk.get('article', '')}_{chunk.get('numeral', '')}"
            points.append(
                {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str)),
                    "vector": embedding,
                    "payload": {

                        "norma":
                        norma,

                        "source":
                        os.path.basename(pdf_path),

                        "titulo":
                        article["titulo"],

                        "capitulo":
                        article["capitulo"],

                        "subcapitulo":
                        article["subcapitulo"],

                        "article":
                        chunk["article"],

                        "numeral":
                        chunk["numeral"],

                        "text":
                        chunk["text"]
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

    for pdf in pdfs:
        build_index(pdf)