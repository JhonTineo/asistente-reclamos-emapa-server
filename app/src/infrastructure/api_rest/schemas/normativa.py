from pydantic import BaseModel, Field


# --- Documentos (ingesta de normativas completas) ---

class VectorizarMarkdownResponse(BaseModel):
    status: str
    coleccion: str
    chunks_procesados: int
    indexados: int


class VectorizarPdfResponse(BaseModel):
    status: str
    message: str
    coleccion: str
    norma: str


class ListarDocumentosResponse(BaseModel):
    status: str
    total: int
    documentos: list[str]


# --- Artículos (mantenimiento puntual dentro de una colección) ---

class ArticuloPunto(BaseModel):
    id: str | int
    payload: dict


class ListarArticulosResponse(BaseModel):
    status: str
    coleccion: str
    total: int
    puntos: list[ArticuloPunto]


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


class ActualizarArticuloResponse(BaseModel):
    status: str
    mensaje: str
    id: str
    id_determinista_calculado: str
    payload: dict


class BuscarArticuloExactoResponse(BaseModel):
    status: str
    id_determinista_calculado: str
    id_real: str | int
    texto_guardado: str
    payload: dict


class EliminarArticuloResponse(BaseModel):
    status: str
    mensaje: str
    id_calculado: str


# --- Búsqueda (consulta usada por frontend/agentes) ---

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


class BuscarPalabraClaveRequest(BaseModel):
    query: str
    coleccion: str | None = "sunass_reglamento"
    top_k: int | None = 15


class PuntoPalabraClave(BaseModel):
    id: str | int
    tipo_coincidencia: str
    score: float
    payload: dict


class BuscarPalabraClaveResponse(BaseModel):
    status: str
    coleccion: str
    palabra_clave_buscada: str
    total_encontrados: int
    coincidencias_exactas: int
    coincidencias_semanticas: int
    puntos: list[PuntoPalabraClave]
