# API — Asistente de Reclamos EMAPA

Guía para el equipo frontend: qué hace cada endpoint, en qué orden llamarlos y
qué esperar de cada uno. Para el detalle exhaustivo de tipos (todos los campos,
sus tipos exactos y validaciones) usa siempre el Swagger autogenerado en
`/docs` — este documento explica el *flujo* y el *porqué*, cosas que Swagger
no muestra.

- **Base URL (desarrollo):** `http://localhost:8000`
- **Swagger UI:** `http://localhost:8000/docs`

---

## 1. Introducción

El backend expone dos procesos de negocio independientes:

1. **Atención de Reclamos** — flujo orquestado de varios pasos: buscar el
   reclamo, investigar los medios probatorios, generar objetivos, concluir el
   informe, proponer una conciliación y emitir la resolución.
2. **Gestión de Normativa** — carga y consulta de los reglamentos (SUNASS u
   otros) que sustentan legalmente las conclusiones del paso anterior.

Todos los endpoints devuelven JSON (salvo los de streaming, que devuelven
NDJSON — ver [sección 5](#5-endpoints-con-streaming-ndjson)).

---

## 2. Autenticación

Dos headers controlan el contexto de cada petición. Ninguno es un login del
usuario final: son configuración por-petición.

| Header | Para qué sirve | Obligatorio |
|---|---|---|
| `Authorization: Bearer <token-emapa>` | Token del sistema EMAPA con el que el backend consulta reclamos, tarjetas de lectura, etc. | **Sí**, solo en `GET /reclamos/reclamo/...` (es el punto de entrada del flujo). En el resto de endpoints es opcional: si no llega, el backend reutiliza el token guardado al buscar el reclamo (o el de `.env` en desarrollo). |
| `X-LLM-Provider` | Proveedor de inferencia a usar (`local`, `openrouter`, `openai`, `gemini`). Ver `GET /modelos/proveedores`. | No — si no llega, se infiere del id del modelo. |
| `X-LLM-Api-Key` | API key del proveedor externo elegido. El backend nunca expone sus propias keys; el frontend manda la del usuario. | No — hay un fallback de key en el servidor para desarrollo. |

**Importante:** el token de EMAPA se guarda en el backend asociado al
`codreclamo` cuando se llama a `GET /reclamos/reclamo/...`. Todos los pasos
posteriores del flujo (investigación, conciliación, resolución) pueden omitir
el header `Authorization` y el backend recupera el token guardado — pero solo
si el server no se reinició entretanto (el store es en memoria).

---

## 3. Flujo típico de uso

```
1. GET  /reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}
        └─ guarda el token EMAPA y crea el informe (vacío) en el store
2. POST /investigacion/objetivos              ─┐
   POST /investigacion/medios-disponibles      ┘  en paralelo
   POST /investigacion/<medio>[/stream]          (uno por cada medio a analizar)
3. POST /investigacion/conclusion[/stream]
        └─ requiere al menos un medio analizado
4. POST /conciliacion/propuesta
        └─ requiere que el informe tenga conclusión + veredicto (paso 3)
5. POST /resolucion
        └─ requiere conclusión + veredicto (paso 3); usa la propuesta del paso 4
```

Los pasos 2 y 3 tienen **dos variantes** (ver [sección 5](#5-endpoints-con-streaming-ndjson)):

- **`/stream`** (NDJSON) — para cuando hay un usuario mirando la pantalla: el
  frontend muestra progreso en vivo (preprocesamiento → resumen del LLM).
- **sin `/stream`** — para flujos automatizados sin usuario presente (p.ej. al
  registrarse un reclamo web, disparar objetivos + análisis de medios
  automáticamente): se espera el resultado completo de una sola vez.

`GET /investigacion/informe/preview` puede llamarse en cualquier momento del
paso 2 para obtener el texto del informe con lo que se ha analizado hasta
ahora.

La **Gestión de Normativa** es independiente de este flujo — se usa para
mantener la base de conocimiento que consume `FundamentacionNormativaAgent`
en el paso de conclusión.

---

## 4. Referencia de endpoints

### 4.1 `reclamos` — prefix `/reclamos`

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}` | Busca el reclamo en EMAPA, guarda el token y crea el informe en el store. **Punto de entrada del flujo.** |
| POST | `/reclamos/clasificar-rapido` | Clasificación por reglas (sin LLM), pensada para reclamos web. Si ya viene `des_cod_reclamo`, lo respeta. |

<details>
<summary>Ejemplo — <code>GET /reclamos/reclamo/...</code></summary>

Respuesta (200):
```json
{
  "codreclamo": "000456",
  "datos": { "...": "respuesta cruda de EMAPA" },
  "informe": {
    "numero": "...",
    "fecha": "2026-07-22",
    "asunto": "...",
    "reclamo": "000456",
    "suministro": "000123",
    "destinatario": null,
    "datos_reclamo": {
      "codcliente": "000123",
      "reclamante": "...",
      "tipo_reclamo": "...",
      "clasificacion_reclamo": "...",
      "motivo_reclamo": "...",
      "meses_reclamados": "...",
      "fecha_recepcion": "...",
      "estado_reclamo": "..."
    }
  },
  "error": null,
  "tiempo": 0.42
}
```
Si el reclamo no existe, `datos` es `null` y `error` trae el mensaje (la
respuesta sigue siendo 200 — el frontend debe chequear `error`, no el status
code, para este endpoint en particular).
</details>

---

### 4.2 `investigacion` — prefix `/investigacion`

Medios probatorios analizables: `inspeccion-externa`, `inspeccion-interna`,
`tarjeta-lectura`, `corte-reapertura`, `record-facturacion`, `saldo-detalle`.

| Método | Ruta | Tag | Descripción |
|---|---|---|---|
| POST | `/investigacion/{medio}/stream` | `interactivo` | Analiza un medio con progreso en vivo (NDJSON). |
| POST | `/investigacion/{medio}` | `automatizacion` | Analiza un medio, espera el resultado completo. |
| POST | `/investigacion/objetivos` | — | Genera los objetivos de investigación a partir del motivo guardado. |
| POST | `/investigacion/medios-disponibles` | — | Verifica en paralelo qué medios traen datos en EMAPA (sin LLM, para habilitar/deshabilitar pestañas en el front). |
| GET | `/investigacion/informe/preview` | — | Texto del informe con lo analizado hasta ahora (sin LLM). |
| POST | `/investigacion/conclusion/stream` | `interactivo` | Fundamenta y concluye el informe, con eventos en vivo por cada problema. |
| POST | `/investigacion/conclusion` | `automatizacion` | Igual, pero espera el resultado completo. |

**Orden importa:** `corte-reapertura`, `record-facturacion` y
`saldo-detalle` requieren que `tarjeta-lectura` se haya analizado antes (fija
la ventana de meses que los demás reutilizan).

<details>
<summary>Ejemplo — <code>POST /investigacion/tarjeta-lectura</code></summary>

Request:
```json
{
  "codsuc": "001",
  "codcliente": "000123",
  "codreclamo": "000456",
  "clasificacion": "CONSUMO ELEVADO",
  "meses": 12,
  "modelo": "qwen3:8b"
}
```
Response (200):
```json
{
  "medio_id": "tarjeta_lectura",
  "medio_nombre": "Tarjeta de Lecturas",
  "resumen": "texto en lenguaje natural del análisis...",
  "datos": { "...": "datos crudos de EMAPA" },
  "problemas": [
    { "tipo": "...", "detalle": "...", "articulos": [], "accion": null, "responsable": null, "base_legal": null }
  ],
  "tiempo": 3.1
}
```
</details>

<details>
<summary>Ejemplo — <code>POST /investigacion/conclusion</code></summary>

Request:
```json
{ "codreclamo": "000456", "clasificacion": "CONSUMO ELEVADO", "modelo": "qwen3:8b" }
```
Errores:
- `404` — no hay informe en curso para ese `codreclamo` (no se buscó el reclamo).
- El campo `problemas[].base_legal` viene fundamentado solo para medios
  **determinantes** (los que definen el veredicto); el resto se incluye sin
  fundamentar para no perder tiempo en artículos irrelevantes.
</details>

---

### 4.3 `conciliacion` — prefix `/conciliacion`

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/conciliacion/propuesta` | Genera la propuesta de conciliación a partir de la conclusión ya guardada en el informe. |

Requiere que el informe tenga `conclusion` y `veredicto` (paso previo: 
`POST /investigacion/conclusion[/stream]`). Si no, responde `409`.

---

### 4.4 `resolucion` — prefix `/resolucion`

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/resolucion` | Genera la resolución final (considerandos redactados por el LLM; el veredicto FUNDADO/INFUNDADO ya viene fijado por la conclusión, no lo decide el LLM). |

Request:
```json
{
  "codreclamo": "000456",
  "propuesta_conciliacion": "texto de la propuesta de la empresa",
  "propuesta_reclamante": "postura del cliente (opcional)",
  "observaciones": "opcional",
  "modelo": "qwen3:8b"
}
```
Igual que conciliación, requiere `conclusion` + `veredicto` ya generados
(`409` si no).

---

### 4.5 `modelos` — prefix `/modelos`

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/modelos/proveedores` | Catálogo de proveedores de inferencia (externos primero, local al final con `disponible`/`motivo` según hardware). Úsalo para poblar el selector de proveedor. |
| GET | `/modelos` | Modelos disponibles (locales Ollama + externos OpenRouter), cada uno con `tipo`. |
| GET | `/modelos/cargados` | Modelos actualmente en memoria (para pintar el botón encendido/apagado). |
| GET | `/modelos/local/estado` | Estado del servidor Ollama local (online, modelos descargados, aptitud de hardware). |
| POST | `/modelos/cargar` | Precarga un modelo en memoria (botón "encender"). |
| POST | `/modelos/descargar` | Libera un modelo de memoria (botón "apagar"). |

---

### 4.6 Normativa — 3 routers bajo `/normativa`

#### `normativa-documentos` — `/normativa/documentos` (ingesta de un reglamento completo)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/normativa/documentos` | Sube un Markdown, lo trocea e indexa como colección nueva. `400` si la colección ya existe. |
| POST | `/normativa/documentos/pdf` | Sube un PDF (`multipart/form-data`: `file`, `coleccion`, `norma`, `is_el_peruano`), extrae texto e indexa. |
| GET | `/normativa/documentos` | Lista las colecciones (reglamentos) cargadas. |

#### `normativa-articulos` — `/normativa/articulos` (mantenimiento puntual de un artículo)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/normativa/articulos?coleccion=...` | Lista todos los artículos de una colección. |
| GET | `/normativa/articulos/buscar?article=...&numeral=...&coleccion=...` | Busca un artículo exacto. `404` si no existe. |
| PUT | `/normativa/articulos` | Crea o actualiza (upsert) un artículo. Body: `{ article, numeral?, text, palabras_clave?, titulo?, capitulo?, subcapitulo?, norma?, coleccion? }`. |
| DELETE | `/normativa/articulos?article=...&numeral=...&coleccion=...` (o `?point_id=...`) | Elimina (lógicamente) un artículo. |

#### `normativa-busqueda` — `/normativa/busqueda` (consulta, usada por el frontend y por `FundamentacionNormativaAgent`)

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/normativa/busqueda` | Búsqueda semántica (embeddings). Body: `{ texto, top_k? }`. Devuelve artículos ordenados por score coseno. |
| POST | `/normativa/busqueda/palabra-clave` | Búsqueda híbrida: coincidencias exactas (substring normalizado) + semánticas. Body: `{ query, coleccion?, top_k? }`. |

---

## 5. Endpoints con streaming (NDJSON)

Los endpoints `/stream` responden `Content-Type: application/x-ndjson`: una
línea JSON por evento (no un solo JSON al final). Léelos con un lector de
stream (`response.body.getReader()` en fetch, o `EventSource`-like manual
parsing por `\n`), no con `response.json()`.

**`POST /investigacion/{medio}/stream`** emite 2 eventos:
```jsonl
{"evento": "preprocesamiento", "medio_id": "...", "datos": {...}, "problemas": [...], "tiempo": 0.8}
{"evento": "resumen", "medio_id": "...", "resumen": "texto del LLM", "tiempo": 3.1}
```

**`POST /investigacion/conclusion/stream`** emite, por cada problema
fundamentado, 2 eventos, y al final 2 más:
```jsonl
{"evento": "inicio", "total_problemas": 4}
{"evento": "articulos", "indice": 0, "medio_id": "...", "articulos": [...]}
{"evento": "fundamentacion", "indice": 0, "medio_id": "...", "accion": "...", "responsable": "...", "base_legal": "..."}
... (se repite por cada problema)
{"evento": "conclusion", "veredicto": "FUNDADO", "conclusion": "..."}
{"evento": "informe", "codreclamo": "...", "informe": "texto final", "problemas": [...], "tiempo": 12.4}
```

Ambos pueden emitir `{"evento": "error", "error": "..."}` en cualquier punto
del stream si algo falla a mitad de camino (la conexión HTTP sigue en 200; el
error viene en el payload, no en el status code).

---

## 6. Modelos de datos compartidos

- **`Informe`** (server-side, en memoria, indexado por `codreclamo`) — el
  estado central del flujo: metadatos del reclamo, bloques por medio
  analizado, objetivos, conclusión, veredicto. Se pierde si el server se
  reinicia (no hay persistencia en disco todavía).
- **`ReclamoSchema`** — datos del reclamante/propietario/motivo, tal como
  vienen de EMAPA.
- **`ProblemaNormadoSchema`** — un hallazgo detectado en un medio: `tipo`,
  `detalle`, `articulos` (recuperados por RAG), y tras la conclusión también
  `accion`, `responsable`, `base_legal`.

Los tipos exactos (opcionalidad, defaults) están en Swagger — esta sección es
solo el mapa mental de cómo se relacionan.

---

## 7. Códigos de error comunes

| Código | Cuándo aparece | Qué hacer en el frontend |
|---|---|---|
| `401` | Falta el token EMAPA en `GET /reclamos/reclamo/...`. | Pedir/renovar el token. |
| `404` | No hay informe en curso para el `codreclamo` (objetivos, medios, conclusión, conciliación, resolución, buscar-articulo). | Guiar al usuario a buscar el reclamo primero. |
| `409` | Se pide conciliación o resolución sin que la conclusión tenga `veredicto` aún. | Bloquear el botón hasta que el paso de conclusión termine. |
| `400` | Body inválido (p.ej. `texto` vacío en búsqueda normativa, colección duplicada al subir un documento). | Mensaje de validación en el form. |
| `503` | El índice vectorial (Qdrant) no responde en `/normativa/busqueda`. | Reintentar / avisar que la búsqueda normativa está caída. |
| `503` / `401` (LLM) | El proveedor de inferencia externo está saturado o la API key es inválida (`X-LLM-Api-Key`). El backend distingue estos casos del 500 genérico. | Sugerir cambiar de modelo/proveedor. |
| `500` | Excepción no controlada. Siempre trae `detail` legible (nunca un stacktrace crudo). | Mostrar el `detail` y loguear para soporte. |

Todas las respuestas de error siguen el formato estándar de FastAPI:
`{ "detail": "mensaje legible" }`.
