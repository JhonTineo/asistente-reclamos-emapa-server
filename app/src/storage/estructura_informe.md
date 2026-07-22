1. Introducción
   - Qué hace la API, base URL, autenticación (header token EMAPA)
2. Autenticación
   - Cómo obtener/pasar el token EMAPA, qué endpoints lo requieren obligatorio vs opcional
3. Flujo típico de uso (el corazón del doc)
   - Diagrama/lista numerada: buscar reclamo → clasificar → analizar medios →
     generar objetivos → concluir → conciliación → resolución
   - Qué endpoints son prerequisito de cuáles
4. Referencia de endpoints (agrupados por router: reclamos, investigacion,
   modelos, embedding_docs)
   - Por cada uno: método+ruta, cuándo usarlo, request/response de ejemplo,
     errores esperados (404 sin informe en curso, 409 sin veredicto, etc.)
5. Streaming endpoints (NDJSON)
   - Cómo consumir /stream (eventos: preprocesamiento/resumen, articulos/
     fundamentacion/conclusion/informe) — esto es no-estándar y necesita
     explicación aparte de Swagger
6. Modelos de datos compartidos (Reclamo, Informe, etc.)
7. Códigos de error comunes