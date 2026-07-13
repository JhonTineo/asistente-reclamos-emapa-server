import logging
import re
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from app.src.application.services.chunck.md_embedding_service import (
    parse_md_to_chunks,
    generar_embeddings,
    indexar_en_qdrant
)
from app.src.application.services.rag.retriever import Retriever

logger = logging.getLogger("api.embedding_docs")
router = APIRouter(prefix="/normativa", tags=["normativa"])

# Colección donde chunk_and_index.py indexa el reglamento SUNASS.
REGLAMENTO_COLLECTION = "sunass_reglamento"

# Usa EmbeddingService (Ollama nomic-embed-text), el mismo modelo con el que
# se indexó, para que el score coseno sea significativo.
retriever = Retriever()


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
