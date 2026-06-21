PYTHON ?= python
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/Scripts/python
UVICORN := $(VENV_DIR)/Scripts/uvicorn

.PHONY: help venv install spacy setup up down restart logs run index test-llm docker-up docker-build docker-down clean deploy

help:
	@echo "Targets disponibles:"
	@echo "  make setup        - Crear venv, instalar dependencias y modelo spaCy"
	@echo "  make up           - Levantar infraestructura local (qdrant + ollama)"
	@echo "  make run          - Ejecutar API FastAPI en modo reload"
	@echo "  make index        - Indexar normativa en Qdrant"
	@echo "  make test-llm     - Ejecutar script test_llm.py"
	@echo "  make docker-build - Levantar stack completo con build"
	@echo "  make docker-down  - Bajar stack completo"
	@echo "  make clean        - Limpiar caches y artefactos temporales"

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -r requirements.txt

spacy: install
	$(VENV_PYTHON) -m spacy download es_core_news_sm

setup: spacy

up:
	docker compose up qdrant ollama -d

down:
	docker compose stop qdrant ollama

restart: down up

logs:
	docker compose logs -f qdrant ollama

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

index:
	$(VENV_PYTHON) -m app.scripts.chunk_and_index
	$(VENV_PYTHON) -m app.scripts.build_reclamos_index

test-llm:
	$(VENV_PYTHON) test_llm.py

docker-up:
	docker compose up -d

docker-build:
	docker compose up --build -d

docker-down:
	docker compose down

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '__pycache__', 'app/__pycache__']]; [p.unlink() for p in pathlib.Path('.').rglob('*.pyc')]"

# Backward compatibility with previous Makefile target.
deploy: setup up