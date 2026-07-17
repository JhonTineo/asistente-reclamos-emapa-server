import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.src.infrastructure.api_rest.modelos import router as modelos_router
from app.src.infrastructure.api_rest.investigacion import router as investigacion_router
from app.src.infrastructure.api_rest.reclamos import router as reclamos_router
from app.src.infrastructure.api_rest.embedding_docs import router as embedding_docs_router
from app.src.application.adapters.llm import ModeloNoCargadoError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# Ver el prompt completo enviado a los agentes (nivel DEBUG solo en estos loggers).
logging.getLogger("agent.analista_medio").setLevel(logging.DEBUG)
logging.getLogger("agent.fundamentacion_normativa").setLevel(logging.DEBUG)
logging.getLogger("agent.objetivos").setLevel(logging.DEBUG)
logging.getLogger("agent.conclusion").setLevel(logging.DEBUG)
logging.getLogger("agent.conciliador").setLevel(logging.DEBUG)
logging.getLogger("agent.resolucion").setLevel(logging.DEBUG)

app = FastAPI(
    title="Asistente Reclamos EMAPA",
    description="API para análisis de reclamos de EMAPA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://127.0.0.1:5173", 
        "http://localhost:3000", 
        "http://127.0.0.1:3000",
        "https://asistente-reclamos-emapa.vercel.app"
        ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(modelos_router)
app.include_router(investigacion_router)
app.include_router(reclamos_router)
app.include_router(embedding_docs_router)

logger = logging.getLogger("api.main")


@app.exception_handler(ModeloNoCargadoError)
async def modelo_no_cargado_handler(request: Request, exc: ModeloNoCargadoError) -> JSONResponse:
    """Sin esto, esta excepción (y cualquiera no controlada) escapa por fuera
    de CORSMiddleware y el navegador la reporta como bloqueo CORS en vez de
    mostrar el error real. Ver /modelos/cargar para encender un modelo."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def excepcion_no_controlada_handler(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad general: cualquier excepción no controlada debe
    devolver una respuesta CON headers CORS (los maneja FastAPI dentro del
    stack de middlewares) en vez de dejarla escapar y que el navegador la
    reporte como un falso bloqueo CORS."""
    logger.exception("[EXCEPCION NO CONTROLADA] %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Error interno: {exc}"})