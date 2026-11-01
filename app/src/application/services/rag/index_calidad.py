# -*- coding: utf-8 -*-
"""Indexa el TUO del Reglamento de Calidad (RCD 058-2023-SUNASS-CD) con
`calidad_chunker` en la colección `sunass_reglamento`, la segunda en la búsqueda
escalonada (después de `sunass_reclamos`).

    # revisar sin red
    python -m app.src.application.services.rag.index_calidad --dry-run

    # indexar (idempotente: los ids son deterministas)
    python -m app.src.application.services.rag.index_calidad

    # reindexar desde cero. OBLIGATORIO si la colección viene del chunker anterior
    # (ids aleatorios): al mezclarse con los nuevos quedarían fragmentos duplicados.
    python -m app.src.application.services.rag.index_calidad --recrear

Los prefijos de tarea del modelo (EMBEDDING_DOCUMENT_PREFIX / EMBEDDING_QUERY_PREFIX)
son uno solo para toda la app: si se cambian hay que reindexar TAMBIÉN `sunass_reclamos`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from app.src.application.services.rag.calidad_chunker import (
    COLECCION_CALIDAD,
    chunkear_calidad,
    validar_calidad,
)
from app.src.application.services.rag.index_reclamos import indexar_chunks
from app.src.application.services.rag.reclamos_chunker import resumen

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PDF_CALIDAD_POR_DEFECTO = os.path.join(
    _SRC_DIR, "storage", "files", "RESOLUCIÓN N_º 058-2023-SUNASS-CD-5-36.pdf"
)


def indexar_calidad(pdf_path: str, store, coleccion: str = COLECCION_CALIDAD,
                    recrear: bool = False, embedder=None) -> dict:
    chunks = chunkear_calidad(pdf_path)
    return indexar_chunks(
        chunks, os.path.basename(pdf_path), store, coleccion, recrear, embedder, validar_calidad(chunks),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", default=PDF_CALIDAD_POR_DEFECTO)
    parser.add_argument("--coleccion", default=COLECCION_CALIDAD)
    parser.add_argument("--recrear", action="store_true", help="borra la colección y la crea de cero")
    parser.add_argument("--dry-run", action="store_true", help="solo chunkea y valida; no usa red")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.dry_run:
        chunks = chunkear_calidad(args.pdf)
        print(resumen(chunks))
        problemas = validar_calidad(chunks)
        for p in problemas:
            print("  ! " + p)
        return 1 if problemas else 0

    from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter

    print(indexar_calidad(args.pdf, QdrantAdapter(), args.coleccion, recrear=args.recrear))
    return 0


if __name__ == "__main__":
    sys.exit(main())
