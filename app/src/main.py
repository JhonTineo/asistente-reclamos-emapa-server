import logging

import openai
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.src.infrastructure.api_rest.modelos import router as modelos_router
from app.src.infrastructure.api_rest.investigacion import router as investigacion_router
from app.src.infrastructure.api_rest.investigacion_stream import router as investigacion_stream_router
from app.src.infrastructure.api_rest.conciliacion import router as conciliacion_router
from app.src.infrastructure.api_rest.resolucion import router as resolucion_router
from app.src.infrastructure.api_rest.reclamos import router as reclamos_router
from app.src.infrastructure.api_rest.normativa_documentos import router as normativa_documentos_router
from app.src.infrastructure.api_rest.normativa_articulos import router as normativa_articulos_router
from app.src.infrastructure.api_rest.normativa_busqueda import router as normativa_busqueda_router
from app.src.application.adapters.llm import ModeloNoCargadoError, InferenciaLocalNoDisponibleError


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# httpx loguea un INFO por cada request saliente (p.ej. el chequeo de versión
# de Qdrant al arrancar). Es ruido, no error: se sube a WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)

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
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "https://asistente-reclamos-emapa.vercel.app"
        ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(modelos_router)
app.include_router(investigacion_router)
app.include_router(investigacion_stream_router)
app.include_router(conciliacion_router)
app.include_router(resolucion_router)
app.include_router(reclamos_router)
app.include_router(normativa_documentos_router)
app.include_router(normativa_articulos_router)
app.include_router(normativa_busqueda_router)

logger = logging.getLogger("api.main")


@app.exception_handler(ModeloNoCargadoError)
async def modelo_no_cargado_handler(request: Request, exc: ModeloNoCargadoError) -> JSONResponse:
    """Sin esto, esta excepción (y cualquiera no controlada) escapa por fuera
    de CORSMiddleware y el navegador la reporta como bloqueo CORS en vez de
    mostrar el error real. Ver /modelos/cargar para encender un modelo."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InferenciaLocalNoDisponibleError)
async def inferencia_local_no_disponible_handler(
    request: Request, exc: InferenciaLocalNoDisponibleError
) -> JSONResponse:
    """El servidor no cumple los requisitos de hardware/estado para ofrecer
    inferencia local (ver GET /modelos/proveedores para el detalle expuesto al
    frontend, que debería impedir seleccionar 'local' en ese caso)."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def _mensaje_proveedor_externo(exc: openai.APIStatusError) -> str:
    """Extrae el mensaje legible que el proveedor (OpenRouter/OpenAI/Gemini)
    manda en el body del error, en vez del dump crudo de la excepción."""
    try:
        body = exc.response.json()
        return (
            body.get("error", {}).get("message")
            or body.get("error", {}).get("metadata", {}).get("raw")
            or str(exc)
        )
    except Exception:
        return str(exc)


@app.exception_handler(openai.RateLimitError)
async def rate_limit_handler(request: Request, exc: openai.RateLimitError) -> JSONResponse:
    """El proveedor externo (frecuente en modelos ':free' de OpenRouter) está
    saturado. Se distingue del 500 genérico para que el frontend pueda avisar
    "prueba otro modelo" en vez de un error interno opaco."""
    msg = _mensaje_proveedor_externo(exc)
    logger.warning("[LLM] Rate limit del proveedor externo: %s", msg)
    return JSONResponse(
        status_code=503,
        content={"detail": f"El proveedor de inferencia está saturado (límite de uso alcanzado): {msg}"},
    )


@app.exception_handler(openai.AuthenticationError)
async def auth_error_handler(request: Request, exc: openai.AuthenticationError) -> JSONResponse:
    """La API key del proveedor (la que manda el frontend, o el fallback del
    backend) es inválida, venció o no tiene permisos."""
    msg = _mensaje_proveedor_externo(exc)
    logger.warning("[LLM] Error de autenticación del proveedor externo: %s", msg)
    return JSONResponse(
        status_code=401,
        content={"detail": f"API key del proveedor de inferencia inválida o sin permisos: {msg}"},
    )


@app.exception_handler(openai.APIStatusError)
async def api_status_error_handler(request: Request, exc: openai.APIStatusError) -> JSONResponse:
    """Cualquier otro error HTTP del proveedor externo (400, 402 sin crédito,
    5xx del propio proveedor, etc.), con el mensaje real en vez de un 500 opaco."""
    msg = _mensaje_proveedor_externo(exc)
    logger.warning("[LLM] Error del proveedor externo (status=%s): %s", exc.status_code, msg)
    return JSONResponse(
        status_code=exc.status_code if 400 <= exc.status_code < 600 else 502,
        content={"detail": f"Error del proveedor de inferencia: {msg}"},
    )


@app.exception_handler(Exception)
async def excepcion_no_controlada_handler(request: Request, exc: Exception) -> JSONResponse:
    """Red de seguridad general: cualquier excepción no controlada debe
    devolver una respuesta CON headers CORS (los maneja FastAPI dentro del
    stack de middlewares) en vez de dejarla escapar y que el navegador la
    reporte como un falso bloqueo CORS."""
    logger.exception("[EXCEPCION NO CONTROLADA] %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Error interno: {exc}"})