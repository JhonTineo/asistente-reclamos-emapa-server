import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.modelos import router as modelos_router
from app.api.investigacion import router as investigacion_router

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
