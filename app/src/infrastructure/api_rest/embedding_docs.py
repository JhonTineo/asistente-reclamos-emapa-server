import logging
import re
import uuid
import os
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field
from app.src.application.services.chunck.md_embedding_service import (
    parse_md_to_chunks,
    generar_embeddings,
    indexar_en_qdrant
)
from app.src.application.services.chunck.chunk_and_index import build_index
from app.src.application.services.rag.retriever import Retriever
from app.src.application.services.rag.qdrant_store import QdrantStore

logger = logging.getLogger("api.embedding_docs")
router = APIRouter(prefix="/normativa", tags=["normativa"])

# Colección donde chunk_and_index.py indexa el reglamento SUNASS.
REGLAMENTO_COLLECTION = "sunass_reglamento"

# Usa EmbeddingService (Ollama nomic-embed-text), el mismo modelo con el que
# se indexó, para que el score coseno sea significativo.
retriever = Retriever()

class BuscarPalabraClaveRequest(BaseModel):
    query: str
    coleccion: str | None = "sunass_reglamento"
    top_k: int | None = 15

class ActualizarArticuloRequest(BaseModel):
    id: str | None = None
    article: str = Field(..., description="Número de artículo, ej: ARTÍCULO 42")
    numeral: str | None = Field(None, description="Numeral, ej: 42.1")
    text: str = Field(..., description="Contenido completo del texto")
    palabras_clave: list[str] | None = []
    titulo: str | None = ""
    capitulo: str | None = ""
    subcapitulo: str | None = ""
    norma: str | None = "Reglamento Calidad Servicios Saneamiento"
    coleccion: str | None = "sunass_reglamento"

class EliminarArticuloRequest(BaseModel):
    article: str = Field(None, description="Número de artículo, ej: ARTÍCULO 42")
    numeral: str | None = Field(None, description="Numeral, ej: 42.1")
    point_id: str | None = Field(None, description="ID directo del punto a eliminar")
    coleccion: str | None = "sunass_reglamento"

class BuscarArticuloExactoRequest(BaseModel):
    article: str = Field(..., description="Número de artículo, ej: ARTÍCULO 42")
    numeral: str | None = Field(None, description="Numeral, ej: 42.1")
    coleccion: str | None = "sunass_reglamento"


class BuscarNormativaRequest(BaseModel):
    texto: str = Field(
        ...,
        min_length=1,
        description="Texto relacionado a calidad de atención a consultar."
    )
    top_k: int = Field(
        5,
        ge=1,
        le=20,
        description="Cantidad de artículos a devolver (por defecto 5)."
    )


class ArticuloRelacionado(BaseModel):
    rank: int
    score: float
    article: str | None = None
    numeral: str | None = None
    titulo: str | None = None
    capitulo: str | None = None
    subcapitulo: str | None = None
    norma: str | None = None
    texto: str | None = None
    source: str | None = None


class BuscarNormativaResponse(BaseModel):
    query: str
    total: int
    resultados: list[ArticuloRelacionado]


def sanitize_filename(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = re.sub(r"[^\w\-]", "_", name)
    return name


@router.post("/vectorizar")
async def vectorizar(file: UploadFile = File(...)):
    texto_md = await file.read()
    logger.info(f"Archivo recibido: {file.filename}, texto: {texto_md.decode('utf-8')} bytes")
    coleccion = sanitize_filename(file.filename)
    
    qdrant = QdrantStore()
    if qdrant.collection_exists(coleccion):
        raise HTTPException(
            status_code=400,
            detail=f"La normativa o reglamento '{coleccion}' ya se encuentra registrada en el sistema."
        )
        
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


@router.post("/vectorizar-pdf")
async def vectorizar_pdf(
    file: UploadFile = File(...),
    coleccion: str = Form(...),
    norma: str = Form(...),
    is_el_peruano: bool = Form(False)
):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="El archivo debe ser un PDF."
        )

    # Save temp file
    temp_path = f"/tmp/{uuid.uuid4()}_{file.filename}"
    try:
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
            
        logger.info(f"Procesando PDF: {file.filename} (Coleccion: {coleccion}, Norma: {norma}, Formato El Peruano: {is_el_peruano})")
        
        # Build index (extracts text, chunks, vectorizes, upserts to Qdrant)
        build_index(
            pdf_path=temp_path,
            coleccion=coleccion,
            norma=norma,
            is_el_peruano=is_el_peruano
        )
        
        return {
            "status": "ok",
            "message": "PDF procesado y vectorizado exitosamente.",
            "coleccion": coleccion,
            "norma": norma
        }
    except Exception as e:
        logger.error(f"Error procesando PDF: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error procesando el PDF: {str(e)}"
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/buscar", response_model=BuscarNormativaResponse)
def buscar(request: BuscarNormativaRequest) -> BuscarNormativaResponse:
    """
    Busca en el reglamento SUNASS los artículos más relacionados con un texto
    sobre calidad de atención. Devuelve los `top_k` resultados ordenados por
    score (similitud coseno) de mayor a menor.
    """
    texto = request.texto.strip()

    if not texto:
        raise HTTPException(
            status_code=400,
            detail="El campo 'texto' no puede estar vacío."
        )

    try:
        results = retriever.retrieve(
            query=texto,
            top_k=request.top_k,
            collection_name=REGLAMENTO_COLLECTION,
        )
    except Exception as e:
        logger.exception("Error en la búsqueda vectorial")
        raise HTTPException(
            status_code=503,
            detail=f"Error consultando el índice vectorial: {e}"
        )

    # Qdrant ya devuelve los puntos ordenados por score (desc) para COSINE.
    resultados = []
    for rank, r in enumerate(results, start=1):
        payload = r["payload"]
        resultados.append(
            ArticuloRelacionado(
                rank=rank,
                score=round(r["score"], 4),
                article=payload.get("article"),
                numeral=payload.get("numeral"),
                titulo=payload.get("titulo"),
                capitulo=payload.get("capitulo"),
                subcapitulo=payload.get("subcapitulo"),
                norma=payload.get("norma"),
                texto=payload.get("text"),
                source=payload.get("source"),
            )
        )

    logger.info(
        "Búsqueda normativa | top_k=%d | resultados=%d | query=%.60s",
        request.top_k, len(resultados), texto
    )

    return BuscarNormativaResponse(
        query=texto,
        total=len(resultados),
        resultados=resultados,
    )

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

@router.post("/actualizar-articulo")
async def actualizar_articulo(request: ActualizarArticuloRequest):
    qdrant = QdrantStore()
    from app.src.application.services.rag.embeddings import EmbeddingService
    embedder = EmbeddingService()
    
    unique_str = f"{request.article}_{request.numeral if request.numeral else 'None'}"
    point_id = request.id or str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))
    
    vector = embedder.encode(request.text)
    
    payload = {
        "norma": request.norma,
        "titulo": request.titulo,
        "capitulo": request.capitulo,
        "subcapitulo": request.subcapitulo,
        "article": request.article,
        "numeral": request.numeral,
        "text": request.text,
        "palabras_clave": request.palabras_clave
    }
    
    qdrant.upsert(
        points=[{
            "id": point_id,
            "vector": vector,
            "payload": payload
        }],
        collection_name=request.coleccion
    )
    
    return {
        "status": "ok",
        "mensaje": "Artículo actualizado/agregado correctamente.",
        "id": point_id,
        "id_determinista_calculado": point_id,
        "payload": payload
    }

@router.post("/buscar-articulo")
async def buscar_articulo(request: BuscarArticuloExactoRequest):
    qdrant = QdrantStore()
    unique_str = f"{request.article}_{request.numeral if request.numeral else 'None'}"
    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))
    
    # Obtener todos los puntos (QdrantStore.get_all) o filtrar por ID
    puntos = qdrant.get_all(collection_name=request.coleccion)
    punto = next((p for p in puntos if p["id"] == point_id), None)
    
    if not punto:
        # Intento de fallback iterando payload
        punto = next((p for p in puntos if p["payload"].get("article") == request.article and p["payload"].get("numeral") == request.numeral), None)
        if not punto:
            raise HTTPException(status_code=404, detail="Artículo no encontrado")
            
    return {
        "status": "ok",
        "id_determinista_calculado": point_id,
        "id_real": punto["id"],
        "texto_guardado": punto["payload"].get("text", punto["payload"].get("texto", "")),
        "payload": punto["payload"]
    }

@router.get("/listar-articulos")
async def listar_articulos(coleccion: str = "sunass_reglamento"):
    qdrant = QdrantStore()
    puntos = qdrant.get_all(collection_name=coleccion)
    return {
        "status": "ok",
        "coleccion": coleccion,
        "total": len(puntos),
        "puntos": puntos
    }

@router.get("/listar-documentos")
async def listar_documentos():
    qdrant = QdrantStore()
    colecciones = qdrant.get_collections()
    return {
        "status": "ok",
        "total": len(colecciones),
        "documentos": colecciones
    }

@router.post("/eliminar-articulo")
async def eliminar_articulo(request: EliminarArticuloRequest):
    qdrant = QdrantStore()
    if request.point_id:
        punto_id = request.point_id
    else:
        if not request.article:
            raise HTTPException(status_code=400, detail="Debe proveer article y numeral, o point_id.")
        unique_str = f"{request.article}_{request.numeral if request.numeral else 'None'}"
        punto_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))
    
    qdrant.delete(point_id=punto_id, collection_name=request.coleccion)
    return {
        "status": "ok",
        "mensaje": f"Artículo (ID: {punto_id}) eliminado físicamente/lógicamente de la colección {request.coleccion}.",
        "id_calculado": punto_id
    }
