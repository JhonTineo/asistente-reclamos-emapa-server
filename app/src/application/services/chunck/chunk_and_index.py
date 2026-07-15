import os
import uuid
import glob
import logging

from dotenv import load_dotenv
load_dotenv()

from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore

from app.src.application.services.chunck.pdf_parser import (
    extract_text_multicolumn,
    split_articles
)

from app.src.application.services.chunck.legal_chunker import (
    split_numerals
)

logger = logging.getLogger(__name__)


def generate_chunk_id(
    article: str | None,
    numeral: str | None = None,
    norma: str = "Reglamento Calidad Servicios Saneamiento"
) -> str:
    key = f"{norma}|art:{article or 'general'}|num:{numeral or 'general'}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, key))


def build_index(pdf_path):
    text = extract_text_multicolumn(
        pdf_path
    )

    articles = split_articles(text)

    embedder = EmbeddingService()

    qdrant = QdrantStore()

    qdrant.create_collection(
        collection_name="sunass_reglamento",
        dimension=embedder.dimension
    )

    points = []

    for article in articles:

        article_number = article["article"]

        chunks = split_numerals(
            article_number,
            article["text"]
        )

        for chunk in chunks:

            embedding = embedder.encode(
                chunk["text"],
            )

            chunk_id = generate_chunk_id(
                chunk["article"],
                chunk["numeral"],
                "Reglamento Calidad Servicios Saneamiento"
            )

            points.append(
                {
                    "id": chunk_id,
                    "vector": embedding,
                    "payload": {

                        "norma":
                        "Reglamento Calidad Servicios Saneamiento",

                        "source":
                        os.path.basename(pdf_path),

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
            collection_name="sunass_reglamento",
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

    BASE_DIR = os.path.dirname(
        os.path.dirname(__file__)
    )

    pdf_path = os.path.join(
        BASE_DIR,
        "..",
        "..",
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
            os.path.join(BASE_DIR, "storage", "files")
        )

    for pdf in pdfs:
        build_index(pdf)