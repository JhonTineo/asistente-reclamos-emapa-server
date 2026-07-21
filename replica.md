# Guía de Implementación: Búsqueda Híbrida (Exacta + Semántica) en Qdrant

Este documento detalla la lógica, el flujo, los archivos modificados y el código exacto que se implementó para crear el endpoint de búsqueda por palabras clave (`/normativa/buscar-palabra-clave`) dentro del servidor FastAPI usando la base de datos vectorial Qdrant.

---

## 1. Archivos Modificados

1. **`app/src/application/services/rag/qdrant_store.py`**
   - **Modificación:** Se añadió el método `search_by_keyword` a la clase `QdrantStore`.
   - **Propósito:** Ejecutar la lógica de búsqueda de forma dual (primero haciendo *scroll* para extraer coincidencias exactas de subcadena ignorando tildes/mayúsculas, y luego haciendo *search* vectorial para coincidencias semánticas).

2. **`app/src/infrastructure/api_rest/embedding_docs.py`**
   - **Modificación:** Se creó el esquema `BuscarPalabraClaveRequest` y la ruta `@router.post("/buscar-palabra-clave")`.
   - **Propósito:** Exponer la función a través de la API REST para que clientes o Postman puedan consultarla con un JSON.

---

## 2. Explicación del Flujo y la Lógica

La búsqueda por palabras clave no se limitó únicamente a la búsqueda vectorial tradicional (embeddings), sino que se diseñó como una **búsqueda híbrida y exhaustiva**:

### A. Normalización de Textos (Cero fallos por tildes o mayúsculas)
Se implementó una función auxiliar `_normalize` utilizando la librería nativa de Python `unicodedata`. Esta función convierte el texto a minúsculas y elimina todas las tildes y caracteres especiales (diacríticos). 
* **Ejemplo:** `"consumo atípico"` y `"Consumo Atipico"` se normalizan ambos a `"consumo atipico"`. Así garantizamos que si el usuario escribe sin tilde en el buscador, igual encuentre el artículo de la base de datos que sí la tiene.

### B. Búsqueda Exacta (Filtro por Subcadena)
El código utiliza `self.client.scroll` de la librería `qdrant-client` para iterar rápidamente (en bloques de 100) por todos los puntos de la colección `sunass_reglamento`. 
En cada iteración, extrae el texto del punto, lo normaliza y verifica si la palabra clave (normalizada) existe textualmente dentro de ese contenido (`if norm_keyword in _normalize(text):`). Todos los que coinciden se guardan en la lista `exact_matches` con un score de `1.0` y la etiqueta `"tipo_coincidencia": "exacta (palabra clave)"`.

### C. Búsqueda Semántica Vectorial (Complemento)
Posteriormente, el código toma la misma palabra clave original, la vectoriza mediante `EmbeddingService().encode(keyword)` y realiza una búsqueda vectorial (`self.search()`). 
A los resultados que superen el score mínimo (`> 0.45`) y que **no estén** ya listados en la búsqueda exacta, se les guarda en la lista `semantic_matches` con la etiqueta `"tipo_coincidencia": "semántica (similitud)"`.

### D. Fusión
Ambas listas (`exact_matches` + `semantic_matches`) se combinan y se retornan en el endpoint, dividiendo para el cliente en el JSON final los conteos específicos de cada tipo.

---

## 3. Código Modificado

### En `qdrant_store.py` (Nueva función en `QdrantStore`)

```python
    def search_by_keyword(
        self,
        keyword: str,
        collection_name: str | None = None,
        top_k: int = 15
    ):
        target_collection = collection_name or self.collection_name
        import unicodedata

        def _normalize(s: str) -> str:
            if not s:
                return ""
            s = unicodedata.normalize('NFKD', str(s))
            return "".join(c for c in s if not unicodedata.combining(c)).lower()

        norm_keyword = _normalize(keyword)

        # 1. Búsqueda exacta (scroll por todos los puntos de la colección para subcadena sin importar mayúsculas/ tildes)
        exact_matches = []
        try:
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=target_collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                for p in results:
                    text = p.payload.get("text", "") if p.payload else ""
                    if norm_keyword in _normalize(text):
                        exact_matches.append({
                            "id": p.id,
                            "tipo_coincidencia": "exacta (palabra clave)",
                            "score": 1.0,
                            "payload": p.payload
                        })
                offset = next_offset
                if not offset or len(results) == 0:
                    break
        except Exception:
            pass

        # 2. Búsqueda semántica vectorial (embeddings) como complemento
        semantic_matches = []
        try:
            from app.src.application.services.rag.embeddings import EmbeddingService
            embedder = EmbeddingService()
            vector = embedder.encode(keyword)
            sem_results = self.search(vector=vector, top_k=top_k, collection_name=target_collection)
            exact_ids = {m["id"] for m in exact_matches}
            for p in sem_results:
                if p["id"] not in exact_ids and p.get("score", 0) > 0.45:
                    semantic_matches.append({
                        "id": p["id"],
                        "tipo_coincidencia": "semántica (similitud)",
                        "score": round(float(p.get("score", 0)), 4),
                        "payload": p.get("payload", {})
                    })
        except Exception:
            pass

        return exact_matches + semantic_matches
```

### En `embedding_docs.py` (Esquema y Endpoint)

```python
from pydantic import BaseModel

class BuscarPalabraClaveRequest(BaseModel):
    query: str
    coleccion: str | None = "sunass_reglamento"
    top_k: int | None = 15

# ... (código existente) ...

@router.post("/buscar-palabra-clave")
async def buscar_palabra_clave(request: BuscarPalabraClaveRequest):
    qdrant = QdrantStore()
    resultados = qdrant.search_by_keyword(
        keyword=request.query,
        collection_name=request.coleccion,
        top_k=request.top_k or 15
    )
    exactos = [r for r in resultados if "exacta" in r.get("tipo_coincidencia", "")]
    semanticos = [r for r in resultados if "semántica" in r.get("tipo_coincidencia", "")]

    return {
        "status": "ok",
        "coleccion": request.coleccion or "sunass_reglamento",
        "palabra_clave_buscada": request.query,
        "total_encontrados": len(resultados),
        "coincidencias_exactas": len(exactos),
        "coincidencias_semanticas": len(semanticos),
        "puntos": resultados
    }
```

---

## 4. Prompt para Replicar estas Lógicas

Si en algún momento futuro tú u otro desarrollador desean replicar esta misma lógica de búsqueda en otra base de datos, en otro proyecto de Qdrant o en otra API (ejemplo en Node.js, Spring Boot, etc.), puedes usar **exactamente este Prompt**:

> **PROMPT PARA EL ASISTENTE (LLM):**
> 
> "Necesito implementar un endpoint REST para buscar documentos o fragmentos de texto dentro de una base de datos vectorial (Qdrant). El requisito indispensable es que la búsqueda debe ser **HÍBRIDA** (exacta + semántica). Sigue esta lógica:
> 
> 1. Crea la ruta `POST /buscar-palabra-clave` (o equivalente) que reciba un JSON con el campo de texto `query`.
> 2. Implementa en el DAO/Store de Qdrant un método llamado `search_by_keyword(keyword)`.
> 3. En ese método, debes incluir una función de normalización que quite las tildes y convierta todo a minúsculas usando `unicodedata` para evitar fallos de coincidencia.
> 4. **Fase 1 (Búsqueda Exacta):** Utiliza el mecanismo de 'scroll' o paginación de la base de datos para recorrer todos los puntos. Extrae su campo de texto (`payload["text"]`), normalízalo, y verifica si la palabra clave (también normalizada) está contenida dentro del texto de manera literal (búsqueda por subcadena). Retorna esos registros con un score manual de 1.0 y una etiqueta de tipo de coincidencia 'exacta'.
> 5. **Fase 2 (Búsqueda Semántica):** Convierte el `query` original a su representación vectorial (embedding) y haz un `search` normal contra la base de datos.
> 6. Filtra los resultados semánticos: elimina aquellos IDs que ya fueron encontrados en la Fase 1 para no tener duplicados, y mantén solo los que superen un threshold de 0.45 de similitud. Asígnales una etiqueta de coincidencia 'semántica'.
> 7. Une ambas listas y envíalas de respuesta al usuario, retornando los conteos totales de cuántos fueron exactos y cuántos semánticos."
