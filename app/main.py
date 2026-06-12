from fastapi import FastAPI
from app.api.reclamos import router as reclamos_router

app = FastAPI(
    title="Asistente Reclamos EMAPA",
    description="MCP Server para clasificación y gestión de reclamos de EMAPA",
    version="0.1.0",
)

app.include_router(reclamos_router)
