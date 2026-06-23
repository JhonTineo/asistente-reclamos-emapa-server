# app/scripts/build_reclamos_index.py

import os
import re
import uuid
import logging

from app.rag.embeddings import EmbeddingService
from app.rag.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tipos_reclamos"


def parse_reclamos(text):

    bloques = re.split(
        r"\n(?=ID:)",
        text.strip()
    )

    registros = []

    for bloque in bloques:

        id_match = re.search(
            r"ID:\s*(.+)",
            bloque
        )

        if not id_match:
            continue

        tipo_match = re.search(
            r"TIPO:\s*(.+)",
            bloque
        )

        subtipo_match = re.search(
            r"SUBTIPO:\s*(.+)",
            bloque
        )

        categoria_match = re.search(
            r"CATEGORIA:\s*(.+)",
            bloque
        )

        definicion_match = re.search(
            r"DEFINICION:\s*([\s\S]+)",
            bloque
        )

        registros.append(
            {
                "codigo": id_match.group(1).strip(),
                "tipo": (
                    tipo_match.group(1).strip()
                    if tipo_match else ""
                ),
                "subtipo": (
                    subtipo_match.group(1).strip()
                    if subtipo_match else ""
                ),
                "categoria": (
                    categoria_match.group(1).strip()
                    if categoria_match else ""
                ),
                "definicion": (
                    definicion_match.group(1).strip()
                    if definicion_match else ""
                )
            }
        )

    return registros


def build_reclamos_index(md_path):

    logger.info(
        "Procesando archivo %s",
        md_path
    )

    with open(
        md_path,
        "r",
        encoding="utf-8"
    ) as f:
        content = f.read()

    registros = parse_reclamos(content)

    logger.info(
        "Registros encontrados: %d",
        len(registros)
    )

    embedder = EmbeddingService()

    qdrant = QdrantStore()

    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        dimension=embedder.dimension
    )

    points = []

    for registro in registros:

        texto_embedding = f"""
        Categoria: {registro['categoria']}
        Tipo: {registro['tipo']}
        Subtipo: {registro['subtipo']}
        Definicion: {registro['definicion']}
        """

        embedding = embedder.encode(
            texto_embedding
        )

        points.append(
            {
                "id": str(uuid.uuid4()),
                "vector": embedding,
                "payload": registro
            }
        )

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )

    logger.info(
        "Categorías indexadas: %d",
        len(points)
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    BASE_DIR = os.path.dirname(
        os.path.dirname(__file__)
    )

    md_path = os.path.join(
        BASE_DIR,
        "storage",
        "anexo1_tipos_reclamos.md"
    )

    if not os.path.exists(md_path):

        logger.warning(
            "No se encontró el archivo Markdown: %s",
            md_path
        )

    else:

        build_reclamos_index(md_path)