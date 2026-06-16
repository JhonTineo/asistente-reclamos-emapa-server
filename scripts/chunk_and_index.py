import os
import uuid
import glob
import logging

from sentence_transformers import SentenceTransformer

from app.tools.vector_db import QdrantStore

from pdf_parser import (
    extract_text_multicolumn,
    split_articles
)

from legal_chunker import (
    split_numerals
)

logger = logging.getLogger(__name__)


MODEL_NAME = "intfloat/multilingual-e5-base"


def build_index(pdf_path):

    logger.info(
        "Procesando %s",
        pdf_path
    )

    text = extract_text_multicolumn(
        pdf_path
    )

    articles = split_articles(text)

    embedder = SentenceTransformer(
        MODEL_NAME
    )

    qdrant = QdrantStore(
        dim=embedder.get_sentence_embedding_dimension()
    )

    qdrant.create_collection()

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
                normalize_embeddings=True
            )

            points.append(
                {
                    "id": str(uuid.uuid4()),
                    "vector": embedding.tolist(),
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
            points[i:i + batch_size]
        )

    logger.info(
        "Chunks indexados: %d",
        len(points)
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    pdfs = glob.glob(
        "./storage/files/*.pdf"
    )

    for pdf in pdfs:
        build_index(pdf)