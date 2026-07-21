from pydantic import BaseModel, Field


class ModeloResponse(BaseModel):
    id: str
    # "local" = corre en Ollama (VPS) | "externo" = corre en la nube (OpenRouter)
    tipo: str = "local"


class ModelosListResponse(BaseModel):
    modelos: list[ModeloResponse]


class ProveedorResponse(BaseModel):
    id: str                        # "local" | "openrouter" | "openai" | "gemini"
    label: str                     # nombre visible
    tipo: str                      # "ollama" | "openai_compat"
    requiere_key: bool             # si el usuario debe ingresar una API key
    modelos: list[str] = Field(default_factory=list)
    disponible: bool = True        # false = no cumple requisitos para elegirse
    motivo_no_disponible: str | None = None


class ProveedoresListResponse(BaseModel):
    proveedores: list[ProveedorResponse]
    # Proveedor que el frontend debe preseleccionar cuando el usuario todavía
    # no configuró nada (sin localStorage previo).
    proveedor_default: str


class ModelosCargadosResponse(BaseModel):
    modelos: list[str] = Field(default_factory=list, description="Modelos actualmente en memoria")


class ModeloAccionRequest(BaseModel):
    modelo: str = Field(description="Nombre del modelo (tal como lo devuelve /modelos)")


class ModeloAccionResponse(BaseModel):
    modelo: str
    ok: bool
    en_memoria: bool
    tiempo: float
    error: str | None = None
