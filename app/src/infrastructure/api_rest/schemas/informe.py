"""Schemas del informe de atención automatizado (orquestador de punta a
punta): búsqueda + objetivos + análisis de medios + conclusión en una sola
llamada (POST /reclamos/informe-atencion)."""

from pydantic import BaseModel, Field

from app.src.infrastructure.api_rest.schemas.investigacion import MedioDisponible


class InformeAutomaticoRequest(BaseModel):
    codsede: str = Field(description="Código de sede")
    codsuc: str = Field(description="Código de sucursal")
    codreclamo: str = Field(description="Código del reclamo")
    codcliente: str = Field(description="Código de cliente")
    meses: int = Field(default=12, description="Ventana de meses a analizar (cada medio calcula la suya)")
    anio: str = Field(default="2026", description="Año para el record de facturación")
    modelo: str | None = None
    sesion_id: str | None = Field(
        default=None,
        description=(
            "Identificador de la pestaña/sesión del frontend. Si otra sesión ya "
            "está atendiendo este reclamo, se rechaza con 409."
        ),
    )
    creado_por: str | None = Field(
        default=None,
        description="Usuario que inició la atención, para organizar la cola.",
    )


class InformeAutomaticoResponse(BaseModel):
    codreclamo: str
    # Resúmenes + conclusión ya combinados en un solo texto (mismo formato que
    # GET /reclamos/{codreclamo}/informe), listo para una caja de texto.
    informe_texto: str
    veredicto: str | None = None
    medios_analizados: list[str] = Field(default_factory=list)
    medios_omitidos: list[MedioDisponible] = Field(default_factory=list)
    tiempo: float
