import logging

from fastapi import APIRouter, HTTPException

from app.src.application.services.rag.retriever import Retriever
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    ArticuloRelacionado,
    BuscarNormativaRequest,
    BuscarNormativaResponse,
    BuscarPalabraClaveRequest,
    BuscarPalabraClaveResponse,
)

logger = logging.getLogger("api.normativa.busqueda")

# Consulta de normativa ya indexada, usada por el frontend y por los agentes
# (fundamentación normativa). Para cargar/mantener normativas, ver
# normativa_documentos.py y normativa_articulos.py.
router = APIRouter(prefix="/normativa/busqueda", tags=["normativa-busqueda"])

REGLAMENTO_COLLECTION = "sunass_reglamento"

# Usa EmbeddingService (Ollama nomic-embed-text), el mismo modelo con el que
# se indexó, para que el score coseno sea significativo.
retriever = Retriever(store=QdrantAdapter())


@router.post("", response_model=BuscarNormativaResponse)
def buscar(request: BuscarNormativaRequest) -> BuscarNormativaResponse:
    """
    Busca en el reglamento SUNASS los artículos más relacionados con un texto
    sobre calidad de atención. Devuelve los `top_k` resultados ordenados por
    score (similitud coseno) de mayor a menor.
    """
    texto = request.texto.strip()

    if not texto:
        raise HTTPException(status_code=400, detail="El campo 'texto' no puede estar vacío.")

    try:
        results = retriever.retrieve(
            query=texto,
            top_k=request.top_k,
            collection_name=REGLAMENTO_COLLECTION,
        )
    except Exception as e:
        logger.exception("Error en la búsqueda vectorial")
        raise HTTPException(status_code=503, detail=f"Error consultando el índice vectorial: {e}")

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

    return BuscarNormativaResponse(query=texto, total=len(resultados), resultados=resultados)


@router.post("/palabra-clave", response_model=BuscarPalabraClaveResponse)
async def buscar_palabra_clave(request: BuscarPalabraClaveRequest) -> BuscarPalabraClaveResponse:
    """Busca por palabra clave: coincidencias exactas (substring normalizado,
    sin tildes/mayúsculas) y semánticas (similitud vectorial) en la colección
    indicada."""
    qdrant = QdrantAdapter()
    resultados = qdrant.search_by_keyword(
        keyword=request.query,
        collection_name=request.coleccion,
        top_k=request.top_k or 15,
    )
    exactos = [r for r in resultados if "exacta" in r.get("tipo_coincidencia", "")]
    semanticos = [r for r in resultados if "semántica" in r.get("tipo_coincidencia", "")]

    return BuscarPalabraClaveResponse(
        status="ok",
        coleccion=request.coleccion or "sunass_reglamento",
        palabra_clave_buscada=request.query,
        total_encontrados=len(resultados),
        coincidencias_exactas=len(exactos),
        coincidencias_semanticas=len(semanticos),
        puntos=resultados,
    )
