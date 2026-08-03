# Asistente de Reclamos EMAPA

Backend de agentes de IA que analiza, sustenta y dictamina reclamos de usuarios
de EMAPA, apoyándose en la normativa SUNASS. Toma un reclamo del sistema
comercial de EMAPA, analiza sus medios probatorios, recupera la normativa
aplicable por búsqueda vectorial (RAG) y emite un informe con veredicto
(**FUNDADO / INFUNDADO**), propuesta de conciliación y resolución.

La inferencia LLM puede correr **en la nube** (varios proveedores compatibles
con la API de OpenAI) o **en local** (Ollama), de forma intercambiable por
petición.

- **Documentación de la API (para frontend):** [`API.md`](API.md)
- **Swagger UI (autogenerado):** `http://localhost:8000/docs`

---

## Arquitectura

El proyecto sigue una arquitectura hexagonal (puertos y adaptadores) bajo
`app/src/`:

```text
app/
├── Dockerfile
├── requirements.txt          # ← única lista de dependencias del proyecto
└── src/
    ├── main.py               # App FastAPI (entrypoint: app.src.main:app)
    ├── core/model/           # Entidades de dominio (reclamo, resolución, ...)
    ├── application/
    │   ├── ports/            # Interfaces (EMAPA, vector DB, proveedor LLM, ...)
    │   ├── services/         # Lógica de negocio (rag, informe, investigación, ...)
    │   └── usecase/agents/   # Agentes de IA (ver abajo)
    ├── infrastructure/
    │   ├── api_rest/         # Routers FastAPI (endpoints)
    │   ├── adapters/         # Implementaciones: EMAPA HTTP, Qdrant, Ollama, OpenAI
    │   └── config/           # settings (pydantic-settings, lee el .env)
    └── storage/files/        # PDFs de normativa a indexar
```

### Componentes clave

| Componente | Rol |
|---|---|
| **FastAPI** | Expone la API REST (sync y streaming NDJSON). |
| **API comercial EMAPA** | Fuente de datos del reclamo: lecturas, facturación, inspecciones, cortes, saldos. |
| **LLM** | Inferencia: externa (OpenRouter, Cerebras, Groq, OpenCode, Cloudflare) o local (Ollama). |
| **Embeddings** | Ollama `nomic-embed-text` (768 dimensiones). |
| **Qdrant** | Vector store del RAG normativo (colección `sunass_reglamento`). |

### Agentes (`app/src/application/usecase/agents/`)

1. **clasificador_rapido** — Clasifica el tipo de reclamo por reglas (sin LLM).
2. **objetivos** — Genera los objetivos de investigación a partir del motivo.
3. **analista_medio** — Analiza cada medio probatorio (preproceso por reglas +
   interpretación del LLM).
4. **recuperador_rag** / **fundamentacion_normativa** — Recuperan la normativa
   SUNASS aplicable en Qdrant y fundamentan los hallazgos determinantes.
5. **conclusion** — Evalúa objetivos vs. hallazgos y fija el veredicto.
6. **conciliador** — Redacta la propuesta de conciliación.
7. **resolucion** — Redacta la resolución final.

El estado de cada atención (`InformeAtencion`) se mantiene **en memoria** del
proceso, indexado por `codreclamo` (no hay base de datos todavía — ver
[`API.md`](API.md) §3).

---

## Requisitos previos

- Python 3.11+
- Docker Desktop (para Qdrant y Ollama)
- Git

---

## Despliegue local (desarrollo)

### 1. Clonar e instalar dependencias

```bash
git clone <url-del-repo>
cd asistente-reclamos-emapa-server

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r app/requirements.txt
```

### 2. Configurar variables de entorno

Copia el ejemplo y completa los valores. El archivo está documentado variable
por variable (proveedores LLM, Ollama, Qdrant, API EMAPA):

```bash
cp .env.example .env
```

Ver [`.env.example`](.env.example) para el detalle de cada variable.

### 3. Levantar Qdrant y Ollama

```bash
docker compose up qdrant ollama -d
```

`docker-compose.override.yml` publica los puertos al host solo en desarrollo
(`6333` Qdrant, `11434` Ollama, `8000` API con hot-reload).

Descargar los modelos que use Ollama (generación + embeddings):

```bash
docker exec ollama ollama pull qwen2.5:3b
docker exec ollama ollama pull nomic-embed-text
```

### 4. Indexar la normativa SUNASS en Qdrant

Coloca el PDF del Reglamento SUNASS en `app/src/storage/files/` y ejecuta:

```bash
python -m app.src.application.services.rag.chunk_and_index
```

> Alternativa vía API: `POST /normativa/documentos/pdf` (multipart) permite
> subir e indexar un reglamento sin usar el script.

### 5. Iniciar la API

```bash
uvicorn app.src.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: **http://localhost:8000/docs**

> Atajos: el [`Makefile`](Makefile) reúne estos pasos (`make setup`, `make up`,
> `make run`, `make index`).

---

## Despliegue completo con Docker Compose

Levanta todo en contenedores (Qdrant + Ollama + API):

```bash
docker compose up --build -d
```

Servicios (`docker-compose.yml`):

- `qdrant`
- `ollama`
- `agent` (FastAPI, imagen construida desde `app/Dockerfile`)

> En este modo, en `.env` usa los nombres de servicio como host:
> `OLLAMA_BASE_URL=http://ollama:11434` y `QDRANT_URL=http://qdrant:6333`.

Luego indexa el reglamento dentro del contenedor:

```bash
docker exec sunass-agent python -m app.src.application.services.rag.chunk_and_index
```

---

## Endpoints principales

La API expone dos procesos de negocio: **atención de reclamos** (flujo
orquestado) y **gestión de normativa** (base de conocimiento del RAG). Resumen:

| Prefijo | Para qué sirve |
|---|---|
| `/reclamos` | Buscar el reclamo, iniciar/orquestar la atención, leer el informe, cerrar. |
| `/investigacion` | Analizar cada medio probatorio, fundamentar y concluir (sync y `/stream`). |
| `/conciliacion` | Generar/editar la propuesta de conciliación. |
| `/resolucion` | Generar/editar la resolución final. |
| `/modelos` | Catálogo y control de modelos/proveedores de inferencia. |
| `/normativa/...` | Ingesta, mantenimiento y búsqueda de la normativa (RAG). |

El detalle completo (rutas, orden de llamada, ejemplos, streaming, errores)
está en [`API.md`](API.md). Los tipos exactos, siempre en `/docs`.

---

## Notas

- La inferencia LOCAL (Ollama) y la EXTERNA (combo de proveedores) son modos
  independientes; se eligen por petición vía headers `X-LLM-Provider` /
  `X-LLM-Api-Key` (ver [`API.md`](API.md) §2).
- Los tests de desarrollo y los `requirements` auxiliares no forman parte del
  despliegue: la única lista de dependencias es `app/requirements.txt`.
