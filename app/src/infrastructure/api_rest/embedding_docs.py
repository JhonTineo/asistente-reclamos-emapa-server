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


from pydantic import BaseModel
from app.src.application.services.chunck.chunk_and_index import generate_chunk_id
from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore


class BuscarArticuloRequest(BaseModel):
    article: str
    numeral: str | None = None
    coleccion: str | None = "sunass_reglamento"


class ActualizarArticuloRequest(BaseModel):
    article: str
    text: str
    numeral: str | None = None
    norma: str = "Reglamento Calidad Servicios Saneamiento"
    source: str = "Modificación EMAPA (API)"
    coleccion: str | None = "sunass_reglamento"


class EliminarArticuloRequest(BaseModel):
    point_id: str | None = None
    article: str | None = None
    numeral: str | None = None
    norma: str = "Reglamento Calidad Servicios Saneamiento"
    coleccion: str | None = "sunass_reglamento"


class BuscarPalabraClaveRequest(BaseModel):
    query: str
    coleccion: str | None = "sunass_reglamento"
    top_k: int | None = 15


@router.post("/buscar-articulo")
async def buscar_articulo(request: BuscarArticuloRequest):
    qdrant = QdrantStore()
    resultados = qdrant.filter_by_article(
        article=request.article,
        numeral=request.numeral,
        collection_name=request.coleccion
    )
    id_determinista = generate_chunk_id(
        request.article,
        request.numeral,
        "Reglamento Calidad Servicios Saneamiento"
    )
    return {
        "status": "ok",
        "coleccion": request.coleccion,
        "id_determinista_calculado": id_determinista,
        "encontrados": len(resultados),
        "puntos": resultados
    }


@router.post("/actualizar-articulo")
async def actualizar_articulo(request: ActualizarArticuloRequest):
    qdrant = QdrantStore()
    embedder = EmbeddingService()

    qdrant.create_collection(
        collection_name=request.coleccion,
        dimension=embedder.dimension
    )

    point_id = generate_chunk_id(
        request.article,
        request.numeral,
        request.norma
    )

    punto_existente = qdrant.get_by_id(point_id, collection_name=request.coleccion)
    operacion = "ACTUALIZADO (MODIFICADO)" if punto_existente else "CREADO (INSERTADO)"

    vector = embedder.encode(request.text)

    payload = {
        "norma": request.norma,
        "source": request.source,
        "article": request.article,
        "numeral": request.numeral,
        "text": request.text
    }

    qdrant.upsert(
        points=[{
            "id": point_id,
            "vector": vector,
            "payload": payload
        }],
        collection_name=request.coleccion
    )

    logger.info(f"Artículo {request.article} (Numeral {request.numeral}) -> {operacion} con ID {point_id}")

    return {
        "status": "ok",
        "operacion": operacion,
        "id": point_id,
        "articulo": request.article,
        "numeral": request.numeral,
        "texto": request.text,
        "coleccion": request.coleccion or "sunass_reglamento"
    }


@router.post("/eliminar-articulo")
async def eliminar_articulo(request: EliminarArticuloRequest):
    qdrant = QdrantStore()
    point_id = request.point_id
    if not point_id and request.article:
        point_id = generate_chunk_id(request.article, request.numeral, request.norma)
    if not point_id:
        return {"status": "error", "message": "Debe especificar point_id o article/numeral para calcularlo."}

    qdrant.delete_by_id(point_id, collection_name=request.coleccion)
    return {
        "status": "ok",
        "operacion": "ELIMINADO",
        "id_eliminado": point_id,
        "coleccion": request.coleccion or "sunass_reglamento"
    }


@router.post("/buscar-palabra-clave")
async def buscar_palabra_clave(request: BuscarPalabraClaveRequest):
    qdrant = QdrantStore()
    resultados = qdrant.search_by_keyword(
        keyword=request.query,
        collection_name=request.coleccion,
        top_k=request.top_k or 15
    )
    exactos = [r for r in resultados if "exacta" in r.get("tipo_coincidencia", "")]
    semanticos = [r for r in resultados if "semántica" in r.get("tipo_coincidencia", "")]

    return {
        "status": "ok",
        "coleccion": request.coleccion or "sunass_reglamento",
        "palabra_clave_buscada": request.query,
        "total_encontrados": len(resultados),
        "coincidencias_exactas": len(exactos),
        "coincidencias_semanticas": len(semanticos),
        "puntos": resultados
    }
