# API — Asistente de Reclamos EMAPA

**Versión 1.0** — primera versión estable de esta documentación.

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
NDJSON — ver [sección 6](#6-endpoints-con-streaming-ndjson)).

---

## 2. Autenticación y sesión

Tres piezas de contexto controlan cada petición. Ninguna es un login del
usuario final: son configuración por-petición.

| Header / parámetro | Para qué sirve | Obligatorio |
|---|---|---|
| `Authorization: Bearer <token-emapa>` | Token del sistema EMAPA con el que el backend consulta reclamos, tarjetas de lectura, etc. | **Sí**, solo en `GET /reclamos/reclamo/...` (es el punto de entrada del flujo). En el resto de endpoints es opcional: si no llega, el backend reutiliza el token guardado al buscar el reclamo (o el de `.env` en desarrollo). |
| `X-LLM-Provider` | Proveedor de inferencia a usar (`local`, `openrouter`, `openai`, `gemini`). Ver `GET /modelos/proveedores`. | No — si no llega, se infiere del id del modelo. |
| `X-LLM-Api-Key` | API key del proveedor externo elegido. El backend nunca expone sus propias keys; el frontend manda la del usuario. | No — hay un fallback de key en el servidor para desarrollo. |
| `sesion_id` (query param en `GET /reclamos/reclamo/...`) | Identificador de la pestaña/sesión del frontend que abre el reclamo (ver [sección 3](#3-ciclo-de-vida-del-informe-en-memoria)). | No, pero sin él no hay protección contra doble atención simultánea. |

El token de EMAPA se guarda en el backend asociado al `codreclamo` cuando se
llama a `GET /reclamos/reclamo/...`. Todos los pasos posteriores del flujo
(investigación, conciliación, resolución) pueden omitir el header
`Authorization` y el backend recupera el token guardado — pero solo si el
informe de ese reclamo sigue en memoria (ver sección siguiente).

---

## 3. Ciclo de vida del informe en memoria

El backend mantiene el estado de cada atención (`InformeAtencion`) **en
memoria del proceso**, indexado por `codreclamo` — no hay base de datos
todavía. Entender su ciclo de vida es clave para no perder trabajo:

```
crear ──► editar/analizar ──► (recargar página) ──► cerrar
 │              │                     │                │
 GET             POST/PATCH            GET              DELETE
 /reclamos/      /investigacion/...    /reclamos/{cod}   /reclamos/{cod}
 reclamo/...     /conciliacion/...     /informe          
                 /resolucion
```

1. **Crear** — `GET /reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}`
   crea el informe vacío (o lo reutiliza si ya existía) y guarda el token EMAPA.
2. **Editar/analizar** — cada paso del flujo (investigar un medio, generar
   objetivos, concluir, proponer conciliación, resolver) va llenando el mismo
   informe en memoria. Los endpoints `PATCH` permiten editar a mano el
   resumen de un medio, la conclusión, la propuesta o la resolución, sin
   invocar al LLM ni borrar lo demás (ver [4.2](#42-investigacion--prefix-investigacion),
   [4.3](#43-conciliacion--prefix-conciliacion), [4.4](#44-resolucion--prefix-resolucion)).
3. **Recargar la página** — `GET /reclamos/{codreclamo}/informe` es una
   lectura pura (sin efectos secundarios) que devuelve todo el estado
   estructurado guardado hasta el momento. El frontend la usa para reconstruir
   la cola de reclamos en atención tras un refresh del navegador.
4. **Cerrar** — `DELETE /reclamos/{codreclamo}` libera el informe y el token
   de la memoria. Se llama al terminar el flujo completo (tras guardar la
   resolución), para no acumular informes de reclamos ya resueltos
   indefinidamente.

**Protección contra doble atención simultánea:** si dos pestañas/ventanas
intentan atender el mismo `codreclamo` a la vez, la segunda búsqueda
(`GET /reclamos/reclamo/...`) responde `409` — a menos que mande el mismo
`sesion_id` que registró la primera (en cuyo caso se interpreta como la misma
pestaña recargando, y se refresca la metadata sin perder el avance ya hecho).
El frontend genera un `sesion_id` propio por cada pestaña de su cola de
reclamos y lo manda como query param.

**Límite importante:** todo esto vive en memoria del proceso. Si el servidor
se reinicia, se pierde el estado de todas las atenciones en curso — no hay
persistencia a disco todavía. Esto es aceptable en el despliegue actual
porque el backend no se redespliega con frecuencia, pero es una limitación a
tener presente.

---

## 4. Referencia de endpoints

### 4.1 `reclamos` — prefix `/reclamos`

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}?sesion_id=` | Busca el reclamo en EMAPA, guarda el token y crea (o reutiliza) el informe en el store. **Punto de entrada del flujo.** `409` si otra sesión ya lo está atendiendo. |
| POST | `/reclamos/clasificar-rapido` | Clasificación por reglas (sin LLM), pensada para reclamos web. Si ya viene `des_cod_reclamo`, lo respeta. |
| GET | `/reclamos/{codreclamo}/informe` | Lectura pura de todo el informe en memoria (metadata, resúmenes por medio, objetivos, conclusión, propuesta, resolución, texto renderizado). Para rehidratar el frontend tras un refresh. `404` si no hay nada en memoria. |
| DELETE | `/reclamos/{codreclamo}` | Cierra la atención: libera el informe y el token de la memoria. |

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
code, para este endpoint en particular). Si el reclamo ya lo está atendiendo
otra sesión, la respuesta es `409` con `{"detail": "El reclamo ... ya se está
atendiendo en otra ventana."}`.
</details>

<details>
<summary>Ejemplo — <code>GET /reclamos/{codreclamo}/informe</code></summary>

Respuesta (200):
```json
{
  "codreclamo": "000456",
  "informe": { "numero": "...", "fecha": "...", "asunto": "...", "reclamo": "...", "suministro": "...", "destinatario": "...", "datos_reclamo": { "...": "..." } },
  "objetivos": [{ "id": 1, "descripcion": "...", "medio": "tarjeta_lectura", "determinante": true }],
  "resumenes": [{ "medio_id": "tarjeta_lectura", "medio_nombre": "Tarjeta de Lecturas", "resumen": "...", "datos": {}, "problemas": [] }],
  "ventana_meses": [[2025, 1], [2025, 2]],
  "veredicto": "FUNDADO",
  "conclusion": "texto de la conclusión...",
  "problemas": [{ "medio_id": "...", "tipo": "...", "detalle": "...", "accion": "...", "responsable": "...", "base_legal": "..." }],
  "propuesta_conciliacion": "texto de la propuesta...",
  "resolucion": "texto de la resolución...",
  "informe_texto": "INFORME N.º ... (texto completo renderizado)"
}
```
Cualquier campo puede venir vacío/`null` si esa parte del flujo aún no se
ejecutó — el frontend usa esto para reconstruir cada sección de a poco.
</details>

---

### 4.2 `investigacion` — prefix `/investigacion`

Medios probatorios analizables: `inspeccion-externa`, `inspeccion-interna`,
`tarjeta-lectura`, `corte-reapertura`, `record-facturacion`, `saldo-detalle`.

| Método | Ruta | Tag | Descripción |
|---|---|---|---|
| POST | `/investigacion/{medio}/stream` | `interactivo` | Analiza un medio con progreso en vivo (NDJSON). |
| POST | `/investigacion/{medio}` | `automatizacion` | Analiza un medio, espera el resultado completo. |
| PATCH | `/investigacion/{medio}/resumen` | — | Edita a mano el resumen de un medio ya analizado (sin LLM). No borra conclusión/propuesta/resolución ya generadas. |
| POST | `/investigacion/objetivos` | — | Genera los objetivos de investigación a partir del motivo guardado. |
| POST | `/investigacion/medios-disponibles` | — | Verifica en paralelo qué medios traen datos en EMAPA (sin LLM, para habilitar/deshabilitar pestañas en el front). |
| GET | `/investigacion/informe/preview` | — | Texto del informe con lo analizado hasta ahora (sin LLM). |
| POST | `/investigacion/conclusion/stream` | `interactivo` | Fundamenta y concluye el informe, con eventos en vivo por cada problema. |
| POST | `/investigacion/conclusion` | `automatizacion` | Igual, pero espera el resultado completo. |
| PATCH | `/investigacion/conclusion` | — | Edita a mano el párrafo de conclusión (sin LLM, sin tocar el veredicto). |

**Orden importa:** `corte-reapertura`, `record-facturacion` y
`saldo-detalle` requieren que `tarjeta-lectura` se haya analizado antes (fija
la ventana de meses que los demás reutilizan).

**Edición manual vs. regenerar:** los endpoints `PATCH` no invocan al LLM ni
invalidan nada aguas abajo — el usuario decide si corrige el texto a mano o
vuelve a llamar al `POST` correspondiente para regenerarlo con IA usando los
datos ya actualizados.

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
<summary>Ejemplo — <code>PATCH /investigacion/tarjeta-lectura/resumen</code></summary>

Request:
```json
{ "codreclamo": "000456", "resumen": "texto corregido a mano..." }
```
Response (200):
```json
{
  "codreclamo": "000456",
  "medio_id": "tarjeta_lectura",
  "resumen": "texto corregido a mano...",
  "informe_texto": "INFORME N.º ... (texto completo re-renderizado con el resumen ya actualizado)"
}
```
`404` si ese medio todavía no se analizó (no hay bloque que editar).
</details>

<details>
<summary>Ejemplo — <code>POST /investigacion/conclusion</code> y <code>PATCH /investigacion/conclusion</code></summary>

`POST` (genera con IA):
```json
{ "codreclamo": "000456", "clasificacion": "CONSUMO ELEVADO", "modelo": "qwen3:8b" }
```
`PATCH` (edición manual):
```json
{ "codreclamo": "000456", "conclusion": "texto de conclusión corregido a mano..." }
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
| POST | `/conciliacion/propuesta` | Genera la propuesta de conciliación a partir de la conclusión ya guardada en el informe. Requiere `conclusion` + `veredicto` (`409` si no). |
| PATCH | `/conciliacion/propuesta` | Edita a mano el texto de la propuesta (sin LLM). |

---

### 4.4 `resolucion` — prefix `/resolucion`

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/resolucion` | Genera la resolución final (considerandos redactados por el LLM; el veredicto FUNDADO/INFUNDADO ya viene fijado por la conclusión, no lo decide el LLM). Requiere `conclusion` + `veredicto` (`409` si no). |
| PATCH | `/resolucion` | Edita a mano el texto de la resolución (sin LLM). |

Request de `POST /resolucion`:
```json
{
  "codreclamo": "000456",
  "propuesta_conciliacion": "texto de la propuesta de la empresa",
  "propuesta_reclamante": "postura del cliente (opcional)",
  "observaciones": "opcional",
  "modelo": "qwen3:8b"
}
```
Request de `PATCH /resolucion`:
```json
{ "codreclamo": "000456", "resolucion": "texto corregido a mano..." }
```

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

## 5. Flujo típico de uso

```
1. GET    /reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}?sesion_id=
          └─ guarda el token EMAPA y crea (o reutiliza) el informe en el store
2. POST   /investigacion/objetivos              ─┐
   POST   /investigacion/medios-disponibles      ┘  en paralelo
   POST   /investigacion/<medio>[/stream]          (uno por cada medio a analizar)
   PATCH  /investigacion/<medio>/resumen           (opcional: corregir a mano)
3. POST   /investigacion/conclusion[/stream]
          └─ requiere al menos un medio analizado
   PATCH  /investigacion/conclusion                (opcional: corregir a mano)
4. POST   /conciliacion/propuesta
          └─ requiere que el informe tenga conclusión + veredicto (paso 3)
   PATCH  /conciliacion/propuesta                  (opcional: corregir a mano)
5. POST   /resolucion
          └─ requiere conclusión + veredicto (paso 3); usa la propuesta del paso 4
   PATCH  /resolucion                              (opcional: corregir a mano)
6. DELETE /reclamos/{codreclamo}
          └─ cierra la atención (tras guardar/exportar la resolución)
```

Los pasos 2 y 3 tienen **dos variantes** (ver [sección 6](#6-endpoints-con-streaming-ndjson)):

- **`/stream`** (NDJSON) — para cuando hay un usuario mirando la pantalla: el
  frontend muestra progreso en vivo (preprocesamiento → resumen del LLM).
- **sin `/stream`** — para flujos automatizados sin usuario presente (p.ej. al
  registrarse un reclamo web, disparar objetivos + análisis de medios
  automáticamente): se espera el resultado completo de una sola vez.

`GET /investigacion/informe/preview` puede llamarse en cualquier momento del
paso 2 para obtener el texto del informe con lo que se ha analizado hasta
ahora. `GET /reclamos/{codreclamo}/informe` (sección 3) devuelve lo mismo
más estructurado, y sirve además para rehidratar el frontend tras un refresh.

La **Gestión de Normativa** (sección 4.6) es independiente de este flujo — se
usa para mantener la base de conocimiento que consume
`FundamentacionNormativaAgent` en el paso de conclusión.

---

## 6. Endpoints con streaming (NDJSON)

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

## 7. Modelos de datos compartidos

- **`InformeAtencion`** (server-side, en memoria, indexado por `codreclamo`) —
  el estado central del flujo: metadatos del reclamo, `bloques` por medio
  analizado, `objetivos`, `conclusion`, `veredicto`, `propuesta_conciliacion`,
  `resolucion`, y `sesion_id` (dueño actual, ver sección 3). Se pierde si el
  servidor se reinicia (no hay persistencia en disco todavía).
- **`ReclamoSchema`** — datos del reclamante/propietario/motivo, tal como
  vienen de EMAPA.
- **`ProblemaNormadoSchema`** — un hallazgo detectado en un medio: `tipo`,
  `detalle`, `articulos` (recuperados por RAG), y tras la conclusión también
  `accion`, `responsable`, `base_legal`.
- **`ResumenMedio`** — el aporte de un medio al informe: `medio_id`,
  `medio_nombre`, `resumen` (editable a mano), `datos` (crudos de EMAPA),
  `problemas` (lista de `ProblemaNormadoSchema`).

Los tipos exactos (opcionalidad, defaults) están en Swagger — esta sección es
solo el mapa mental de cómo se relacionan.

---

## 8. Códigos de error comunes

| Código | Cuándo aparece | Qué hacer en el frontend |
|---|---|---|
| `401` | Falta el token EMAPA en `GET /reclamos/reclamo/...`. | Pedir/renovar el token. |
| `404` | No hay informe en curso para el `codreclamo` (objetivos, medios, conclusión, conciliación, resolución, ediciones `PATCH`, `GET /reclamos/{cod}/informe`, `buscar-articulo`). | Guiar al usuario a buscar el reclamo primero, o quitarlo de la cola si es una rehidratación fallida. |
| `409` | (a) Se pide conciliación o resolución sin que la conclusión tenga `veredicto` aún. (b) Se busca un reclamo que ya está siendo atendido por otra sesión (`sesion_id` distinto). | (a) Bloquear el botón hasta que el paso de conclusión termine. (b) Avisar al usuario y no reintentar automáticamente. |
| `400` | Body inválido (p.ej. `texto` vacío en búsqueda normativa, colección duplicada al subir un documento). | Mensaje de validación en el form. |
| `503` | El índice vectorial (Qdrant) no responde en `/normativa/busqueda`. | Reintentar / avisar que la búsqueda normativa está caída. |
| `503` / `401` (LLM) | El proveedor de inferencia externo está saturado o la API key es inválida (`X-LLM-Api-Key`). El backend distingue estos casos del 500 genérico. | Sugerir cambiar de modelo/proveedor. |
| `500` | Excepción no controlada. Siempre trae `detail` legible (nunca un stacktrace crudo). | Mostrar el `detail` y loguear para soporte. |

Todas las respuestas de error siguen el formato estándar de FastAPI:
`{ "detail": "mensaje legible" }`.
