import logging
import re
from fastapi import APIRouter, UploadFile, File
from app.src.application.services.chunck.md_embedding_service import (
    parse_md_to_chunks,
    generar_embeddings,
    indexar_en_qdrant
)

logger = logging.getLogger("api.embedding_docs")
router = APIRouter(prefix="/normativa", tags=["normativa"])


def sanitize_filename(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"[^\w\-]", "_", name)
    return name


@router.post("/vectorizar")
async def vectorizar(file: UploadFile = File(...)):
    texto_md = await file.read()
    logger.info(f"Archivo recibido: {file.filename}, texto: {texto_md.decode('utf-8')} bytes")
    coleccion = sanitize_filename(file.filename)
    chunks, metadata = parse_md_to_chunks(texto_md.decode("utf-8"))
    vectores = generar_embeddings(chunks)
    indexados = indexar_en_qdrant(chunks, vectores, metadata, coleccion)
    logger.info(f"Documentos indexados en colección '{coleccion}': {indexados}")
    return {
        "status": "ok",
        "coleccion": coleccion,
        "chunks_procesados": len(chunks),
        "indexados": indexados
    }
