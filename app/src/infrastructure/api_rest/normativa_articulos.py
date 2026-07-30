import logging

from fastapi import APIRouter, HTTPException, Query

from app.src.application.services.rag.legal_chunker import (
    normalizar_numero_articulo,
    calcular_point_id,
    split_numerals,
)
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    ActualizarArticuloRequest,
    ActualizarArticuloResponse,
    BuscarArticuloExactoResponse,
    EliminarArticuloResponse,
    ListarArticulosResponse,
    NumeralInsertado,
    ReemplazarArticuloRequest,
    ReemplazarArticuloResponse,
)

logger = logging.getLogger("api.normativa.articulos")

# Mantenimiento manual de artículos puntuales dentro de una colección ya
# cargada. Para subir una normativa completa, ver normativa_documentos.py.
router = APIRouter(prefix="/normativa/articulos", tags=["normativa-articulos"])


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
    art_clean = normalizar_numero_articulo(article)
    num_clean = numeral if numeral else None
    point_id = calcular_point_id(article, numeral)

    puntos = qdrant.get_all(collection_name=coleccion)
    punto = next((p for p in puntos if p["id"] == point_id), None)
    if not punto:
        # Fallback iterando payload (por si el ID determinista no coincide,
        # p.ej. artículos cargados con un ID propio).
        punto = next(
            (p for p in puntos
             if normalizar_numero_articulo(p["payload"].get("article", "")) == art_clean
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
    """Crea o actualiza (upsert) un artículo/numeral puntual en la colección.

    Para reescribir un artículo completo que estaba dividido en numerales, usar
    `POST /normativa/articulos/reemplazar` (evita numerales viejos huérfanos)."""
    qdrant = QdrantAdapter()
    from app.src.application.services.rag.embeddings import EmbeddingService
    embedder = EmbeddingService()

    art_clean = normalizar_numero_articulo(request.article)
    num_clean = request.numeral if request.numeral else None
    point_id = request.id or calcular_point_id(request.article, request.numeral)

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
        "estado": "vigente",
        "modificado_por": request.modificado_por,
        "vigencia_desde": request.vigencia_desde,
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


@router.post("/reemplazar", response_model=ReemplazarArticuloResponse)
async def reemplazar_articulo(request: ReemplazarArticuloRequest) -> ReemplazarArticuloResponse:
    """Reemplaza un artículo COMPLETO.

    1. Desactiva (soft-delete) todos los numerales vigentes del artículo.
    2. Re-trocea el texto nuevo en numerales y los inserta con IDs deterministas.

    Es la operación correcta cuando una modificatoria reescribe un artículo que
    estaba partido en numerales, porque garantiza que no quede texto viejo
    conviviendo con el nuevo."""
    qdrant = QdrantAdapter()
    from app.src.application.services.rag.embeddings import EmbeddingService
    embedder = EmbeddingService()

    art_clean = normalizar_numero_articulo(request.article)

    # 1) Desactivar la versión previa completa del artículo.
    desactivados = qdrant.deactivate_article(art_clean, collection_name=request.coleccion)

    # 2) Re-trocear el texto nuevo en numerales y reinsertar.
    chunks = split_numerals(art_clean, request.text.strip())

    points = []
    insertados = []
    for chunk in chunks:
        point_id = calcular_point_id(chunk["article"], chunk["numeral"])
        vector = embedder.encode(chunk["text"])
        points.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "norma": request.norma,
                    "titulo": request.titulo,
                    "capitulo": request.capitulo,
                    "subcapitulo": request.subcapitulo,
                    "article": art_clean,
                    "numeral": chunk["numeral"],
                    "text": chunk["text"],
                    "palabras_clave": request.palabras_clave,
                    "estado": "vigente",
                    "modificado_por": request.modificado_por,
                    "vigencia_desde": request.vigencia_desde,
                },
            }
        )
        insertados.append(NumeralInsertado(id=point_id, numeral=chunk["numeral"]))

    qdrant.upsert(points=points, collection_name=request.coleccion)

    return ReemplazarArticuloResponse(
        status="ok",
        mensaje=(
            f"Artículo {art_clean} reemplazado: {len(desactivados)} numeral(es) "
            f"desactivado(s), {len(insertados)} insertado(s)."
        ),
        article=art_clean,
        desactivados=desactivados,
        insertados=insertados,
    )


@router.delete("", response_model=EliminarArticuloResponse)
async def eliminar_articulo(
    article: str | None = Query(None, description="Número de artículo, ej: ARTÍCULO 42"),
    numeral: str | None = Query(None, description="Numeral, ej: 42.1"),
    point_id: str | None = Query(None, description="ID directo del punto a eliminar"),
    todo_el_articulo: bool = Query(
        False, description="Si es true, deroga TODOS los numerales del artículo."
    ),
    coleccion: str = Query("sunass_reglamento"),
) -> EliminarArticuloResponse:
    """Deroga (soft-delete) un artículo. Modos:

    - `todo_el_articulo=true` + `article`: deroga el artículo completo (todos sus numerales).
    - `article` (+ `numeral`): deroga ese numeral puntual.
    - `point_id`: deroga ese punto directamente."""
    qdrant = QdrantAdapter()

    if todo_el_articulo:
        if not article:
            raise HTTPException(status_code=400, detail="Debe proveer 'article' para derogar el artículo completo.")
        ids = qdrant.deactivate_article(article, collection_name=coleccion)
        return EliminarArticuloResponse(
            status="ok",
            mensaje=f"Artículo {normalizar_numero_articulo(article)} derogado: {len(ids)} numeral(es) desactivado(s) en la colección {coleccion}.",
            id_calculado=", ".join(ids) if ids else "(sin numerales activos)",
        )

    if point_id:
        punto_id = point_id
    else:
        if not article:
            raise HTTPException(status_code=400, detail="Debe proveer article y numeral, o point_id.")
        punto_id = calcular_point_id(article, numeral)

    qdrant.delete(point_id=punto_id, collection_name=coleccion)
    return EliminarArticuloResponse(
        status="ok",
        mensaje=f"Artículo (ID: {punto_id}) derogado lógicamente de la colección {coleccion}.",
        id_calculado=punto_id,
    )
