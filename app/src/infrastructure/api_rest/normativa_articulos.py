import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    ActualizarArticuloRequest,
    ActualizarArticuloResponse,
    BuscarArticuloExactoResponse,
    EliminarArticuloResponse,
    ListarArticulosResponse,
)

logger = logging.getLogger("api.normativa.articulos")

# Mantenimiento manual de artículos puntuales dentro de una colección ya
# cargada. Para subir una normativa completa, ver normativa_documentos.py.
router = APIRouter(prefix="/normativa/articulos", tags=["normativa-articulos"])


def extract_article_number(article_str: str) -> str:
    if not article_str:
        return ""
    match = re.search(r"ART[IÍ]CULO\s+(\w+)", article_str, re.I)
    if match:
        return match.group(1)
    return article_str.strip()


def _calcular_point_id(article: str, numeral: str | None) -> str:
    """ID determinista (uuid5) a partir de artículo + numeral, para que subir
    el mismo artículo dos veces haga upsert en vez de duplicar."""
    art_clean = extract_article_number(article)
    num_clean = numeral if numeral else None
    unique_str = f"{art_clean}_{num_clean if num_clean else 'None'}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))


@router.get("", response_model=ListarArticulosResponse)
async def listar_articulos(coleccion: str = "sunass_reglamento") -> ListarArticulosResponse:
    """Lista todos los artículos (puntos) indexados en una colección."""
    qdrant = QdrantAdapter()
    puntos = qdrant.get_all(collection_name=coleccion)
    return ListarArticulosResponse(status="ok", coleccion=coleccion, total=len(puntos), puntos=puntos)


@router.get("/buscar", response_model=BuscarArticuloExactoResponse)
async def buscar_articulo(
    article: str = Query(..., description="Número de artículo, ej: ARTÍCULO 42"),
    numeral: str | None = Query(None, description="Numeral, ej: 42.1"),
    coleccion: str = Query("sunass_reglamento"),
) -> BuscarArticuloExactoResponse:
    """Busca un artículo exacto por número (+ numeral opcional) en una colección."""
    qdrant = QdrantAdapter()
    art_clean = extract_article_number(article)
    num_clean = numeral if numeral else None
    point_id = _calcular_point_id(article, numeral)

    puntos = qdrant.get_all(collection_name=coleccion)
    punto = next((p for p in puntos if p["id"] == point_id), None)
    if not punto:
        # Fallback iterando payload (por si el ID determinista no coincide,
        # p.ej. artículos cargados con un ID propio).
        punto = next(
            (p for p in puntos
             if extract_article_number(p["payload"].get("article", "")) == art_clean
             and p["payload"].get("numeral") == num_clean),
            None,
        )
        if not punto:
            raise HTTPException(status_code=404, detail="Artículo no encontrado")

    return BuscarArticuloExactoResponse(
        status="ok",
        id_determinista_calculado=point_id,
        id_real=punto["id"],
        texto_guardado=punto["payload"].get("text", punto["payload"].get("texto", "")),
        payload=punto["payload"],
    )


@router.put("", response_model=ActualizarArticuloResponse)
async def actualizar_articulo(request: ActualizarArticuloRequest) -> ActualizarArticuloResponse:
    """Crea o actualiza (upsert) un artículo en la colección indicada."""
    qdrant = QdrantAdapter()
    from app.src.application.services.rag.embeddings import EmbeddingService
    embedder = EmbeddingService()

    art_clean = extract_article_number(request.article)
    num_clean = request.numeral if request.numeral else None
    point_id = request.id or _calcular_point_id(request.article, request.numeral)

    vector = embedder.encode(request.text)

    payload = {
        "norma": request.norma,
        "titulo": request.titulo,
        "capitulo": request.capitulo,
        "subcapitulo": request.subcapitulo,
        "article": art_clean,
        "numeral": num_clean,
        "text": request.text,
        "palabras_clave": request.palabras_clave,
    }

    qdrant.upsert(
        points=[{"id": point_id, "vector": vector, "payload": payload}],
        collection_name=request.coleccion,
    )

    return ActualizarArticuloResponse(
        status="ok",
        mensaje="Artículo actualizado/agregado correctamente.",
        id=point_id,
        id_determinista_calculado=point_id,
        payload=payload,
    )


@router.delete("", response_model=EliminarArticuloResponse)
async def eliminar_articulo(
    article: str | None = Query(None, description="Número de artículo, ej: ARTÍCULO 42"),
    numeral: str | None = Query(None, description="Numeral, ej: 42.1"),
    point_id: str | None = Query(None, description="ID directo del punto a eliminar"),
    coleccion: str = Query("sunass_reglamento"),
) -> EliminarArticuloResponse:
    """Elimina (lógicamente) un artículo, por `point_id` directo o por
    `article` + `numeral`."""
    if point_id:
        punto_id = point_id
    else:
        if not article:
            raise HTTPException(status_code=400, detail="Debe proveer article y numeral, o point_id.")
        punto_id = _calcular_point_id(article, numeral)

    qdrant = QdrantAdapter()
    qdrant.delete(point_id=punto_id, collection_name=coleccion)
    return EliminarArticuloResponse(
        status="ok",
        mensaje=f"Artículo (ID: {punto_id}) eliminado físicamente/lógicamente de la colección {coleccion}.",
        id_calculado=punto_id,
    )
