import logging

from fastapi import APIRouter, HTTPException

from app.src.application.services.rag.normativa_escalonada import BuscadorNormativo, fuentes_configuradas
from app.src.application.services.rag.retriever import Retriever
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    ArticuloRelacionado,
    BuscarEscalonadaResponse,
    BuscarNormativaRequest,
    BuscarNormativaResponse,
    BuscarPalabraClaveRequest,
    BuscarPalabraClaveResponse,
    NivelEscalonado,
)
from app.src.infrastructure.config.settings import settings

logger = logging.getLogger("api.normativa.busqueda")

# Consulta de normativa ya indexada, usada por el frontend y por los agentes
# (fundamentación normativa). Para cargar/mantener normativas, ver
# normativa_documentos.py y normativa_articulos.py.
router = APIRouter(prefix="/normativa/busqueda", tags=["normativa-busqueda"])

# Usa EmbeddingService (Ollama nomic-embed-text), el mismo modelo con el que
# se indexó, para que el score coseno sea significativo.
retriever = Retriever(store=QdrantAdapter())


def _buscador(top_k: int) -> BuscadorNormativo:
    return BuscadorNormativo(
        retriever=retriever,
        store=retriever.store,
        fuentes=fuentes_configuradas(settings.normativa_fuentes),
        top_k=top_k,
        umbral=settings.normativa_umbral_score,
    )


@router.post("", response_model=BuscarNormativaResponse)
def buscar(request: BuscarNormativaRequest) -> BuscarNormativaResponse:
    """
    Busca en la normativa SUNASS los artículos más relacionados con un texto.
    Con `coleccion` consulta solo esa colección; sin ella busca por niveles,
    como Yumi: primero atención de reclamos y, si nada supera el umbral,
    calidad. Devuelve los `top_k` resultados ordenados por score (similitud
    coseno) de mayor a menor.
    """
    texto = request.texto.strip()

    if not texto:
        raise HTTPException(status_code=400, detail="El campo 'texto' no puede estar vacío.")

    try:
        if request.coleccion:
            results = retriever.retrieve(
                query=texto, top_k=request.top_k, collection_name=request.coleccion,
            )
        else:
            results = _buscador(request.top_k).buscar_desde(lambda _fuente: texto)
    except Exception as e:
        logger.exception("Error en la búsqueda vectorial")
        raise HTTPException(status_code=503, detail=f"Error consultando el índice vectorial: {e}")

    resultados = _a_articulos_relacionados(results, request.coleccion)

    logger.info(
        "Búsqueda normativa | top_k=%d | resultados=%d | query=%.60s",
        request.top_k, len(resultados), texto
    )

    return BuscarNormativaResponse(query=texto, total=len(resultados), resultados=resultados)


def _a_articulos_relacionados(results: list[dict], coleccion: str | None = None) -> list[ArticuloRelacionado]:
    # Qdrant ya devuelve los puntos ordenados por score (desc) para COSINE.
    # La búsqueda por niveles anota cada resultado con su fuente; si no, `coleccion`.
    resultados = []
    for rank, r in enumerate(results, start=1):
        payload = r["payload"]
        fuente = r.get("fuente")
        resultados.append(
            ArticuloRelacionado(
                rank=rank,
                score=round(r["score"], 4),
                coleccion=fuente.coleccion if fuente else coleccion,
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
    return resultados


@router.post("/escalonada", response_model=BuscarEscalonadaResponse)
def buscar_escalonada(request: BuscarNormativaRequest) -> BuscarEscalonadaResponse:
    """Muestra cómo decide la búsqueda escalonada SIN usar el LLM: consulta todas
    las normas configuradas (`NORMATIVA_FUENTES`, en orden de prioridad), devuelve
    el top-k de cada una con su score y marca cuál se elegiría (la primera con
    algún artículo por encima del umbral). Sirve para calibrar el umbral y para
    comprobar que el Reglamento de Reclamos se consulta antes que el de Calidad."""
    texto = request.texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="El campo 'texto' no puede estar vacío.")

    buscador = _buscador(request.top_k)
    niveles: list[NivelEscalonado] = []
    elegida: str | None = None
    for nivel, fuente in enumerate(buscador.fuentes):
        disponible = buscador.disponible(fuente)
        try:
            results = retriever.retrieve(query=texto, top_k=request.top_k, collection_name=fuente.coleccion) \
                if disponible else []
        except Exception as e:
            logger.exception("Error en la búsqueda vectorial")
            raise HTTPException(status_code=503, detail=f"Error consultando '{fuente.coleccion}': {e}")
        supera = any(r["score"] >= buscador.umbral for r in results)
        if supera and elegida is None:
            elegida = fuente.coleccion
        niveles.append(NivelEscalonado(
            nivel=nivel, coleccion=fuente.coleccion, norma=fuente.nombre_corto,
            disponible=disponible, umbral=buscador.umbral, supera_umbral=supera,
            resultados=_a_articulos_relacionados(results, fuente.coleccion),
        ))
    return BuscarEscalonadaResponse(query=texto, coleccion_elegida=elegida, niveles=niveles)


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
