import logging

from fastapi import FastAPI
from app.api.reclamos import router as reclamos_router
from app.api.modelos import router as modelos_router
from app.api.investigacion import router as investigacion_router
import app.tools.emapa_api  # noqa: F401 - Register EMAPA tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="Asistente Reclamos EMAPA",
    description="MCP Server para clasificación y gestión de reclamos de EMAPA",
    version="0.1.0",
)

app.include_router(modelos_router)
app.include_router(reclamos_router)
app.include_router(investigacion_router)
