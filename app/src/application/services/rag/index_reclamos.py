# -*- coding: utf-8 -*-
"""Crea/actualiza la colección `sunass_reclamos` (TUO del Reglamento General de
Reclamos, RCD 015-2023-SUNASS-CD) en Qdrant.

Uso (desde la raíz del backend, con Qdrant y Ollama levantados):

    # 1) revisar los chunks sin tocar la red (ni embeddings ni Qdrant)
    python -m app.src.application.services.rag.index_reclamos --dry-run

    # 2) indexar (idempotente: los ids son deterministas, re-correr actualiza)
    python -m app.src.application.services.rag.index_reclamos

    # 3) reindexar desde cero (p. ej. tras cambiar de modelo de embeddings)
    python -m app.src.application.services.rag.index_reclamos --recrear

El modelo de embeddings es el mismo que usa la consulta (EmbeddingService) y
queda registrado en el payload de cada punto (`embedding_model`). Lo que se
vectoriza es `ChunkNormativo.texto_embedding()`; los prefijos de tarea del
modelo (EMBEDDING_DOCUMENT_PREFIX) los aplica `EmbeddingService.encode_documents`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from app.src.application.ports.vector_db_port import PuertoBaseVectorial
from app.src.application.services.rag.reclamos_chunker import (
    COLECCION_RECLAMOS,
    ChunkNormativo,
    chunkear_reclamos,
    resumen,
    validar,
)

logger = logging.getLogger(__name__)

# rag -> services -> application -> src
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PDF_RECLAMOS_POR_DEFECTO = os.path.join(
    _SRC_DIR, "storage", "files", "reclamos", "RECLAMOS-RESOLUCION-015-2023-SUNASS-CD.pdf"
)

TAMANO_LOTE = 32


def indexar_chunks(
    chunks: list[ChunkNormativo],
    source: str,
    store: PuertoBaseVectorial,
    coleccion: str,
    recrear: bool = False,
    embedder=None,
    problemas: list[str] | None = None,
) -> dict:
    """Chunks validados -> embeddings por lotes -> upsert en Qdrant.

    `problemas` es el resultado de la validación de quien llama: si no está vacío
    no se gastan embeddings ni se escribe en Qdrant (un id duplicado, por ejemplo,
    pisaría un artículo real)."""
    if problemas:
        raise ValueError("Chunks inválidos, no se indexa:\n  - " + "\n  - ".join(problemas))

    if embedder is None:
        from app.src.application.services.rag.embeddings import EmbeddingService
        embedder = EmbeddingService()

    if recrear and store.collection_exists(coleccion):
        store.delete_collection(coleccion)
    store.create_collection(coleccion, embedder.dimension)

    indexados = 0
    for i in range(0, len(chunks), TAMANO_LOTE):
        lote = chunks[i:i + TAMANO_LOTE]
        vectores = embedder.encode_documents([c.texto_embedding() for c in lote])
        store.upsert(
            [
                {
                    "id": c.point_id(),
                    "vector": v,
                    "payload": {**c.payload(source), "embedding_model": embedder.model_name},
                }
                for c, v in zip(lote, vectores)
            ],
            collection_name=coleccion,
        )
        indexados += len(lote)
        logger.info("Indexados %d/%d", indexados, len(chunks))

    return {
        "coleccion": coleccion,
        "chunks": len(chunks),
        "indexados": indexados,
        "modelo_embeddings": embedder.model_name,
        "dimension": embedder.dimension,
        "prefijo_documento": getattr(embedder, "document_prefix", ""),
    }


def indexar_reclamos(
    pdf_path: str,
    store: PuertoBaseVectorial,
    coleccion: str = COLECCION_RECLAMOS,
    recrear: bool = False,
    embedder=None,
) -> dict:
    """PDF del TUO de Reclamos -> colección."""
    chunks = chunkear_reclamos(pdf_path)
    return indexar_chunks(
        chunks, os.path.basename(pdf_path), store, coleccion, recrear, embedder, validar(chunks),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", default=PDF_RECLAMOS_POR_DEFECTO)
    parser.add_argument("--coleccion", default=COLECCION_RECLAMOS)
    parser.add_argument("--recrear", action="store_true", help="borra la colección y la crea de cero")
    parser.add_argument("--dry-run", action="store_true", help="solo chunkea y valida; no usa red")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.dry_run:
        chunks = chunkear_reclamos(args.pdf)
        print(resumen(chunks))
        problemas = validar(chunks)
        for p in problemas:
            print("  ! " + p)
        return 1 if problemas else 0

    # Punto de composición: acá sí se elige el adaptador concreto.
    from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter

    resultado = indexar_reclamos(args.pdf, QdrantAdapter(), args.coleccion, recrear=args.recrear)
    print(resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
