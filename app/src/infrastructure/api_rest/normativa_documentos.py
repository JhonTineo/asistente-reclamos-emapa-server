import logging
import os
import re
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.src.application.services.rag.md_embedding_service import (
    parse_md_to_chunks,
    generar_embeddings,
    indexar_en_qdrant,
)
from app.src.application.services.rag.chunk_and_index import build_index
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    VectorizarMarkdownResponse,
    VectorizarPdfResponse,
    ListarDocumentosResponse,
)

logger = logging.getLogger("api.normativa.documentos")

# Ingesta de normativas completas (un documento -> una colección en Qdrant).
# Para mantenimiento de un artículo puntual dentro de una colección ya
# cargada, ver normativa_articulos.py.
router = APIRouter(prefix="/normativa/documentos", tags=["normativa-documentos"])


def sanitize_filename(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"[^\w\-]", "_", name)
    return name


@router.post("", response_model=VectorizarMarkdownResponse)
async def cargar_markdown(file: UploadFile = File(...)) -> VectorizarMarkdownResponse:
    """Sube un documento en Markdown, lo trocea y lo indexa como una nueva
    colección en Qdrant (el nombre de la colección se deriva del nombre del
    archivo). Falla con 400 si la colección ya existe."""
    texto_md = await file.read()
    logger.info(f"Archivo recibido: {file.filename}, texto: {texto_md.decode('utf-8')} bytes")
    coleccion = sanitize_filename(file.filename)

    qdrant = QdrantAdapter()
    if qdrant.collection_exists(coleccion):
        raise HTTPException(
            status_code=400,
            detail=f"La normativa o reglamento '{coleccion}' ya se encuentra registrada en el sistema."
        )

    chunks, metadata = parse_md_to_chunks(texto_md.decode("utf-8"))
    vectores = generar_embeddings(chunks)
    indexados = indexar_en_qdrant(chunks, vectores, metadata, coleccion, store=qdrant)
    logger.info(f"Documentos indexados en colección '{coleccion}': {indexados}")
    return VectorizarMarkdownResponse(
        status="ok",
        coleccion=coleccion,
        chunks_procesados=len(chunks),
        indexados=indexados,
    )


@router.post("/pdf", response_model=VectorizarPdfResponse)
async def cargar_pdf(
    file: UploadFile = File(...),
    coleccion: str = Form(...),
    norma: str = Form(...),
    is_el_peruano: bool = Form(False),
) -> VectorizarPdfResponse:
    """Sube un documento en PDF, extrae el texto, lo trocea y lo indexa en la
    colección indicada."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")

    temp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info(
            f"Procesando PDF: {file.filename} (Coleccion: {coleccion}, Norma: {norma}, "
            f"Formato El Peruano: {is_el_peruano})"
        )

        build_index(
            pdf_path=temp_path,
            store=QdrantAdapter(),
            coleccion=coleccion,
            norma=norma,
            is_el_peruano=is_el_peruano,
        )

        return VectorizarPdfResponse(
            status="ok",
            message="PDF procesado y vectorizado exitosamente.",
            coleccion=coleccion,
            norma=norma,
        )
    except Exception as e:
        logger.error(f"Error procesando PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error procesando el PDF: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("", response_model=ListarDocumentosResponse)
async def listar_documentos() -> ListarDocumentosResponse:
    """Lista las colecciones (normativas/documentos) cargadas en Qdrant."""
    qdrant = QdrantAdapter()
    colecciones = qdrant.get_collections()
    return ListarDocumentosResponse(status="ok", total=len(colecciones), documentos=colecciones)
