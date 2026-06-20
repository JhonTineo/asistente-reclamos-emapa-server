<<<<<<< Updated upstream
=======
# Asistente de Reclamos SUNASS (Modelos Locales)

Proyecto de agentes para analizar, sustentar y dictaminar reclamos de usuarios usando normativa SUNASS.

Todo el flujo esta orientado a ejecucion local (FastAPI + Ollama + Qdrant), sin depender de modelos remotos para inferencia.

## Arquitectura actual

```text
app/
|
+-- agents/
|   +-- analizador.py
|   +-- normativo.py
|   +-- dictaminador.py
|
+-- rag/
|   +-- embeddings.py
|   +-- retriever.py
|   +-- qdrant_store.py
|
+-- core/
|   +-- llm.py
|   +-- config.py
|
+-- schemas/
|   +-- reclamo.py
|   +-- dictamen.py
|
+-- orchestrator/
	 +-- workflow.py

ollama/
|
+-- models/
|
+-- cache/

qdrant_storage/
|
+-- aliases/
|
+-- collections


```

## Flujo funcional del reclamo

1. Agente Analizador (`app/agents/analizador.py`)
	- Entiende el reclamo.
	- Extrae hechos relevantes.
	- Identifica tipo/tema y servicio.

2. Agente Normativo (`app/agents/normativo.py`)
	- Construye consulta semantica con analisis estructurado.
	- Consulta Qdrant por similitud vectorial.
	- Recupera Top 5 articulos SUNASS.

3. Agente Dictaminador (`app/agents/dictaminador.py`)
	- Analiza normativa y evidencias.
	- Determina si el reclamo procede o no procede.
	- Genera sustento en formato JSON.

4. Orquestador (`app/orchestrator/workflow.py`)
	- Encadena analisis -> recuperacion normativa -> dictamen.

## Modelos locales previstos

- Extraccion de entidades/hechos: spaCy (y extension futura GLiNER).
- Embeddings para RAG: BGE-M3.
- LLM local para dictamen: Qwen3 8B o Llama 3.1 8B via Ollama.

## Variables de entorno recomendadas

- `OLLAMA_BASE_URL` (default: `http://ollama:11434`)
- `OLLAMA_GENERATOR_MODEL` (ejemplo: `qwen3:8b`)
- `QDRANT_URL` (ejemplo: `http://localhost:6333`)
- `QDRANT_COLLECTION_NAME` (default: `sunass_reglamento`)
- `EMBEDDING_MODEL` (default: `BAAI/bge-m3`)
- `SPACY_MODEL` (default: `es_core_news_sm`)

## Despliegue local (desarrollo)

### Requisitos previos

- Python 3.11+
- Docker Desktop corriendo
- Git

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd asistente-reclamos-emapa-server
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python -m spacy download es_core_news_sm
```

### 3. Configurar variables de entorno

Copiar el archivo de ejemplo y completar los valores:

```bash
cp .env.example .env   # si no existe, crear .env manualmente
```

Contenido minimo del `.env` para desarrollo local:

```env
# LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_GENERATOR_MODEL=qwen3:8b

# Vector DB
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=sunass_reglamento

# Embeddings
EMBEDDING_MODEL=BAAI/bge-m3

# spaCy
SPACY_MODEL=es_core_news_sm

# EMAPA backend (obtener token actualizado del sistema EMAPA)
EMAPA_API_BASE_URL=https://comercial.emapasanmartin.com:8889/sysco-comercial/backend
EMAPA_ACCESS_TOKEN=<token-jwt-emapa>

# Requerido por Settings (puede ser cualquier valor en dev local)
OPENCODE_GO_API_KEY=local-dev
```

### 4. Levantar Qdrant y Ollama con Docker

```bash
docker compose up qdrant ollama -d
```

Verificar que Qdrant esta activo:

```bash
curl http://localhost:6333/
```

### 5. Descargar el modelo LLM en Ollama

```bash
# Qwen3 8B (~5 GB, descarga unica)
docker exec ollama ollama pull qwen3:8b

# Alternativa mas liviana
docker exec ollama ollama pull llama3.1:8b
```

Verificar modelos disponibles:

```bash
docker exec ollama ollama list
```

### 6. Indexar la normativa SUNASS en Qdrant

Colocar el PDF del Reglamento SUNASS en `app/storage/files/` y ejecutar:

```bash
python -m app.scripts.chunk_and_index
```

Este paso descargara el modelo de embeddings BGE-M3 (~2.3 GB) la primera vez.

### 7. Iniciar la API en modo desarrollo

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI disponible en: **http://localhost:8000/docs**

---

## Despliegue completo con Docker Compose

Para correr todo en contenedores (incluida la API):

```bash
docker compose up --build
```

Esto levanta:
- `qdrant` en `localhost:6333`
- `ollama` en `localhost:11434`
- `sunass-agent` (FastAPI) en `localhost:8000`

> Nota: Al usar Docker Compose completo, cambiar en `.env`:
> `OLLAMA_BASE_URL=http://ollama:11434`
> `QDRANT_URL=http://qdrant:6333`

Luego indexar el reglamento desde dentro del contenedor:

```bash
docker exec sunass-agent python -m app.scripts.chunk_and_index
```

---

## Endpoints principales

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/reclamos/clasificar` | Clasifica un reclamo por tipo |
| POST | `/investigacion/iniciar` | Flujo completo: analisis + normas + dictamen |
| POST | `/investigacion/planificar` | Solo planificacion |
| GET | `/modelos` | Lista modelos disponibles |

Ejemplo de request a `/investigacion/iniciar`:

```json
{
  "suministro_id": "001-000123",
  "codsede": "001",
  "codsuc": "001",
  "codcliente": "000123",
  "codreclamo": "000456",
  "anio": "2025",
  "detalle_reclamo": "No estoy conforme con el cobro de los recibos del 2025, ya que mis consumos son de 23 m3 aproximadamente."
}
```

---

## Notas

- Se limpiaron imports heredados en rutas activas.
- La carpeta legacy anterior fue eliminada completamente para cerrar la migracion.
- Para nuevas funcionalidades, usar `app/agents/` y `app/orchestrator/workflow.py`.
>>>>>>> Stashed changes
