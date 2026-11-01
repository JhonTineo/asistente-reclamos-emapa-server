import logging
import os
import re
import tempfile
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.src.application.services.rag.md_embedding_service import (
    parse_md_to_chunks,
    generar_embeddings,
    indexar_en_qdrant,
)
from app.src.application.services.rag.calidad_chunker import COLECCION_CALIDAD
from app.src.application.services.rag.chunk_and_index import build_index
from app.src.application.services.rag.index_calidad import indexar_calidad
from app.src.application.services.rag.index_reclamos import indexar_reclamos
from app.src.application.services.rag.reclamos_chunker import COLECCION_RECLAMOS
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

ESTRUCTURAS = ("auto", "generica", "reclamos_tuo", "calidad_tuo")
# Las dos colecciones de la búsqueda escalonada se cargan siempre con su chunker
# propio: el genérico rompe ligaturas, pierde los preámbulos de los artículos y
# deja fragmentos sueltos (ver DIAGNOSTICO_RAG.md).
_ESTRUCTURA_POR_COLECCION = {COLECCION_RECLAMOS: "reclamos_tuo", COLECCION_CALIDAD: "calidad_tuo"}


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
    logger.info(f"Archivo recibido: {file.filename}, {len(texto_md)} bytes")
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
    estructura: str = Form(
        "auto",
        description="'auto' (por defecto): 'sunass_reclamos' usa 'reclamos_tuo', 'sunass_reglamento' usa "
                    "'calidad_tuo' y cualquier otra colección usa 'generica'. 'reclamos_tuo' = TUO del "
                    "Reglamento de Reclamos (RCD 015-2023-SUNASS-CD); 'calidad_tuo' = TUO del "
                    "Reglamento de Calidad (RCD 058-2023-SUNASS-CD); 'generica' = reglamento con "
                    "artículos de otra norma (un punto por artículo). Con las dos primeras el nombre "
                    "`norma` no se usa: la norma la fija el chunker.",
    ),
    recrear: bool = Form(False),
) -> VectorizarPdfResponse:
    """Sube un documento en PDF, extrae los artículos y los indexa en la colección
    indicada: las dos normas de Yumi (reclamos y calidad) con su troceador propio
    (un punto por numeral) y cualquier otra con el genérico (un punto por artículo).

    `recrear=true` borra la colección antes de indexar: úsalo para reconstruir
    la base desde cero y evitar duplicados de una indexación previa."""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")
    if estructura not in ESTRUCTURAS:
        raise HTTPException(status_code=400, detail=f"'estructura' debe ser una de: {', '.join(ESTRUCTURAS)}.")
    if estructura == "auto":
        estructura = _ESTRUCTURA_POR_COLECCION.get(coleccion, "generica")

    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.filename}")
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info(
            f"Procesando PDF: {file.filename} (Coleccion: {coleccion}, Norma: {norma}, "
            f"Formato El Peruano: {is_el_peruano})"
        )

        if estructura == "reclamos_tuo":
            indexar_reclamos(temp_path, QdrantAdapter(), coleccion=coleccion, recrear=recrear)
        elif estructura == "calidad_tuo":
            indexar_calidad(temp_path, QdrantAdapter(), coleccion=coleccion, recrear=recrear)
        else:
            build_index(
                pdf_path=temp_path,
                store=QdrantAdapter(),
                coleccion=coleccion,
                norma=norma,
                is_el_peruano=is_el_peruano,
                recrear=recrear,
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
