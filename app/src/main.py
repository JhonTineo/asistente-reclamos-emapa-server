import logging
import threading

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
from app.src.infrastructure.api_rest.evidencias import router as evidencias_router
from app.src.infrastructure.api_rest.normativa_documentos import router as normativa_documentos_router
from app.src.infrastructure.api_rest.normativa_articulos import router as normativa_articulos_router
from app.src.infrastructure.api_rest.normativa_busqueda import router as normativa_busqueda_router
from app.src.infrastructure.api_rest.normativa_reconstruccion import router as normativa_reconstruccion_router
from app.src.infrastructure.api_rest.persistencia_middleware import PersistenciaCasosMiddleware
from app.src.infrastructure.adapters.persistencia.sqlite_caso_repository import SqliteCasoRepository
from app.src.infrastructure.config.settings import settings
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.infrastructure.adapters.skills.skill_file_repository import repositorio_skills
from app.src.application.services.rag.embeddings import precalentar as precalentar_embeddings
from contextlib import asynccontextmanager
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# httpx loguea un INFO por cada request saliente (p.ej. el chequeo de versión
# de Qdrant al arrancar). Es ruido, no error: se sube a WARNING.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Por defecto la consola muestra una línea [TIEMPOS] por llamada al LLM y por
# fase (tiempo, tokens reales y cacheados): lo necesario para optimizar. El
# prompt completo y la respuesta cruda ya se guardan en llamadas_llm (yumi.db);
# para verlos también en consola: YUMI_LOG_DETALLE=true.
if settings.yumi_log_detalle:
    for _nombre in ("paso.analisis_medio", "paso.fundamentacion", "paso.objetivos",
                    "paso.conclusion", "paso.conciliacion", "paso.resolucion", "contexto",
                    "tools.llm.openai_compat", "tools.llm.ollama"):
        logging.getLogger(_nombre).setLevel(logging.DEBUG)

_RUTA_DB_POR_DEFECTO = Path(__file__).resolve().parents[2] / "volumes" / "yumi_db" / "yumi.db"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Activa la memoria del caso persistente, recupera las atenciones que
    quedaron abiertas antes del último reinicio y conecta el constructor de
    contexto con las skills y con el registro de llamadas al LLM."""
    skills = repositorio_skills()
    errores_skills = skills.errores()
    logging.getLogger("main").info(
        "Skills: %d cargadas | reemplazos en %s | errores=%d",
        len(skills.todas()), skills.directorio_reemplazos or "(desactivados)", len(errores_skills),
    )
    repo = None
    if settings.yumi_db_path.strip().lower() != "desactivado":
        ruta = settings.yumi_db_path.strip() or str(_RUTA_DB_POR_DEFECTO)
        repo = SqliteCasoRepository(ruta)
        recuperados = informe_store.configurar_persistencia(repo)
        logging.getLogger("main").info(
            "Memoria del caso en %s | atenciones abiertas recuperadas=%d", ruta, recuperados,
        )
    # Sin base de datos no se registran las llamadas (registro=None).
    constructor_contexto.configurar(skills=skills, registro=repo)
    # Carga el modelo de embeddings en Ollama sin bloquear el arranque: la
    # primera fundamentación ya no paga la carga del modelo.
    threading.Thread(target=precalentar_embeddings, name="precalentar-embeddings",
                     daemon=True).start()
    try:
        yield
    finally:
        constructor_contexto.configurar(registro=None)
        if repo is not None:
            informe_store.persistir_cambios()
            informe_store.configurar_persistencia(None)
            repo.cerrar_conexion()


app = FastAPI(
    title="Asistente Reclamos EMAPA",
    description="API para análisis de reclamos de EMAPA",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(PersistenciaCasosMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:5000",
        "https://asistente-reclamos-emapa.vercel.app",
        "https://asistente-reclamos-emapa-ng.vercel.app",
        "https://comercial.emapasanmartin.com:8443",
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
app.include_router(evidencias_router)
app.include_router(normativa_documentos_router)
app.include_router(normativa_articulos_router)
app.include_router(normativa_busqueda_router)
app.include_router(normativa_reconstruccion_router)

logger = logging.getLogger("api.main")


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