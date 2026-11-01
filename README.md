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
| **Embeddings** | Ollama `qwen3-embedding:0.6b` (1024 dimensiones), con la instrucción de consulta de `.env.example`. |
| **Qdrant** | Vector store del RAG normativo: `sunass_reclamos` (Reglamento de Reclamos, se consulta primero) y `sunass_reglamento` (Reglamento de Calidad, respaldo). |

### Agentes (`app/src/application/usecase/agents/`)

1. **clasificador_rapido** — Clasifica el tipo de reclamo por reglas (sin LLM).
2. **objetivos** — Genera los objetivos de investigación a partir del motivo.
3. **analista_medio** — Analiza cada medio probatorio (preproceso por reglas +
   interpretación del LLM).
4. **fundamentacion_normativa** — Recupera la normativa SUNASS aplicable en
   Qdrant (primero el Reglamento de Reclamos y, si no alcanza, el de Calidad) y
   fundamenta los hallazgos determinantes.
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
make up    # = docker compose -f docker-compose.yml -f docker-compose.dev.yml up qdrant ollama -d
```

`docker-compose.dev.yml` publica los puertos al host solo en desarrollo (`6333`
Qdrant, `11434` Ollama). Con una GPU NVIDIA usa `make up-gpu` (suma
`docker-compose.gpu.yml`): indexar las dos normas toma ~45 s en vez de varios
minutos de CPU.

Descargar los modelos que use Ollama (generación + embeddings):

```bash
docker exec ollama ollama pull qwen2.5:3b
docker exec ollama ollama pull qwen3-embedding:0.6b
```

### 4. Indexar la normativa SUNASS en Qdrant

Yumi busca primero en el Reglamento de Reclamos (`sunass_reclamos`) y solo si no
alcanza para argumentar pasa al de Calidad (`sunass_reglamento`). Los PDF ya están
en el repo (`app/src/storage/files/`). Con Qdrant y Ollama arriba:

```bash
python -m app.src.application.services.rag.index_reclamos --recrear
python -m app.src.application.services.rag.index_calidad --recrear
# o ambos:  make index
```

Si se cambia el modelo o los prefijos de embeddings (`.env`) hay que reindexar las
dos. Medición de la búsqueda: `python -m app.test.rag.evaluar_busqueda --modo qdrant`
(ver [`DIAGNOSTICO_RAG.md`](DIAGNOSTICO_RAG.md) y [`CAMBIOS_RAG.md`](CAMBIOS_RAG.md)).

> Alternativa vía API: `POST /normativa/documentos/pdf` (multipart) permite
> subir e indexar un reglamento sin usar el script. Con `coleccion=sunass_reclamos`
> o `sunass_reglamento` usa el troceador propio de cada norma (`estructura=auto`);
> con cualquier otra colección, el genérico.

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

Luego indexa las dos normas dentro del contenedor (descarga antes el modelo de
embeddings: `docker exec ollama ollama pull qwen3-embedding:0.6b`):

```bash
docker exec yumi-agent python -m app.src.application.services.rag.index_reclamos --recrear
docker exec yumi-agent python -m app.src.application.services.rag.index_calidad --recrear
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
