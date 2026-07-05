import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.src.infrastructure.api_rest.modelos import router as modelos_router
from app.src.infrastructure.api_rest.investigacion import router as investigacion_router
from app.src.infrastructure.api_rest.reclamos import router as reclamos_router
from app.src.infrastructure.api_rest.embedding_docs import router as embedding_docs_router 


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

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