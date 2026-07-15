# Reporte de Pruebas - Endpoints de Normativa

**Fecha:** 15 de julio de 2026
**Servidor:** http://localhost:8000 (Docker: sunass-agent)
**Coleccion:** `sunass_reglamento`
**Estado general:** Todas las pruebas PASARON

---

## Correccion aplicada antes de las pruebas

### 1. Variable de entorno `QDRANT_URL` (docker-compose.yml)
**Problema:** El contenedor `sunass-agent` intentaba conectarse a Qdrant via `http://localhost:6333`, pero dentro de Docker ese hostname apunta al propio contenedor, no al servicio `qdrant`.

**Solucion:** Se agrego `QDRANT_URL=http://qdrant:6333` en la seccion `environment` del servicio `agent` en `docker-compose.yml`.

### 2. Auto-creacion de coleccion en `actualizar-articulo` (embedding_docs.py)
**Problema:** El endpoint `POST /normativa/actualizar-articulo` hacia `upsert` sin verificar si la coleccion existia, provocando error 404 de Qdrant.

**Solucion:** Se agrego llamada a `qdrant.create_collection()` al inicio del endpoint, igual que lo hace `chunk_and_index.py`.

### 3. Ruta de busqueda de PDFs (chunk_and_index.py)
**Problema:** El script buscaba PDFs en `/app/src/application/services/storage/files/` pero el archivo real estaba en `/app/src/storage/files/`.

**Solucion:** Se ajusto la ruta relativa con `"..", ".."` para llegar a `/app/src/storage/files/`.

---

## Prueba 1: Creacion con ID Determinista

**Endpoint:** `POST /normativa/actualizar-articulo`
**Objetivo:** Verificar que al enviar un articulo nuevo, el sistema genera un UUIDv5 determinista, crea el embedding y lo guarda en Qdrant.

**Request:**
```json
{
  "article": "24",
  "numeral": "24.1",
  "text": "El usuario de los servicios de saneamiento de EMAPA tiene derecho a interponer su reclamo dentro del plazo de noventa (90) dias calendario de vencido el recibo.",
  "norma": "Reglamento Calidad Servicios Saneamiento",
  "source": "Prueba de Modificacion EMAPA 2026",
  "coleccion": "sunass_reglamento"
}
```

**Response (HTTP 200):**
```json
{
  "status": "ok",
  "operacion": "CREADO (INSERTADO)",
  "id": "c860243c-851f-5b62-bc54-c74766e9b7fc",
  "articulo": "24",
  "numeral": "24.1",
  "texto": "El usuario de los servicios de saneamiento de EMAPA tiene derecho a interponer su reclamo dentro del plazo de noventa (90) dias calendario de vencido el recibo.",
  "coleccion": "sunass_reglamento"
}
```

**Resultado:** PASS - El UUID determinista `c860243c-851f-5b62-bc54-c74766e9b7fc` fue calculado correctamente desde `uuid5(NAMESPACE_DNS, "Reglamento Calidad Servicios Saneamiento|art:24|num:24.1")`.

---

## Prueba 2: Upsert / Cero Duplicados

**Endpoint:** `POST /normativa/actualizar-articulo`
**Objetivo:** Verificar que enviar el mismo articulo con texto modificado NO crea un duplicado, sino que sobrescribe el existente.

**Request (texto modificado: "sesenta" en lugar de "noventa"):**
```json
{
  "article": "24",
  "numeral": "24.1",
  "text": "El usuario de los servicios de saneamiento de EMAPA tiene derecho a interponer su reclamo dentro del plazo de sesenta (60) dias calendario de vencido el recibo.",
  "norma": "Reglamento Calidad Servicios Saneamiento",
  "source": "Prueba de Modificacion EMAPA 2026",
  "coleccion": "sunass_reglamento"
}
```

**Response (HTTP 200):**
```json
{
  "status": "ok",
  "operacion": "ACTUALIZADO (MODIFICADO)",
  "id": "c860243c-851f-5b62-bc54-c74766e9b7fc",
  "articulo": "24",
  "numeral": "24.1",
  "texto": "El usuario de los servicios de saneamiento de EMAPA tiene derecho a interponer su reclamo dentro del plazo de sesenta (60) dias calendario de vencido el recibo.",
  "coleccion": "sunass_reglamento"
}
```

**Resultado:** PASS - El ID es identico al de la Prueba 1 (`c860243c-...`). La operacion indico `ACTUALIZADO (MODIFICADO)` confirmando que se reemplazo el payload y vector sin duplicar.

---

## Prueba 3: Consulta indexada por articulo/numeral

**Endpoint:** `POST /normativa/buscar-articulo`
**Objetivo:** Verificar que se puede buscar un articulo especifico y que existe exactamente 1 registro (sin duplicados).

**Request:**
```json
{
  "article": "24",
  "numeral": "24.1",
  "coleccion": "sunass_reglamento"
}
```

**Response (HTTP 200):**
```json
{
  "status": "ok",
  "coleccion": "sunass_reglamento",
  "id_determinista_calculado": "c860243c-851f-5b62-bc54-c74766e9b7fc",
  "encontrados": 1,
  "puntos": [
    {
      "id": "c860243c-851f-5b62-bc54-c74766e9b7fc",
      "payload": {
        "norma": "Reglamento Calidad Servicios Saneamiento",
        "source": "Prueba de Modificacion EMAPA 2026",
        "article": "24",
        "numeral": "24.1",
        "text": "El usuario de los servicios de saneamiento de EMAPA tiene derecho a interponer su reclamo dentro del plazo de sesenta (60) dias calendario de vencido el recibo."
      }
    }
  ]
}
```

**Resultado:** PASS - `encontrados: 1` confirma cero duplicados. El texto refleja la ultima modificacion ("sesenta (60) dias"). El `id_determinista_calculado` coincide con el ID almacenado.

---

## Prueba 4: Eliminacion de articulos

**Endpoint:** `POST /normativa/eliminar-articulo`
**Objetivo:** Verificar que se puede eliminar un articulo de Qdrant por article/numeral y que luego no aparece en busquedas.

**Request:**
```json
{
  "article": "24",
  "numeral": "24.1",
  "coleccion": "sunass_reglamento"
}
```

**Response (HTTP 200):**
```json
{
  "status": "ok",
  "operacion": "ELIMINADO",
  "id_eliminado": "c860243c-851f-5b62-bc54-c74766e9b7fc",
  "coleccion": "sunass_reglamento"
}
```

**Verificacion posterior (buscar-articulo):**
```json
{
  "status": "ok",
  "coleccion": "sunass_reglamento",
  "id_determinista_calculado": "c860243c-851f-5b62-bc54-c74766e9b7fc",
  "encontrados": 0,
  "puntos": []
}
```

**Resultado:** PASS - La eliminacion fue exitosa. La busqueda posterior confirma `encontrados: 0`, verificando que el punto fue removido limpiamente de Qdrant.

---

## Prueba 5: Indexacion masiva desde PDF

**Script:** `python -m app.src.application.services.chunck.chunk_and_index`
**Objetivo:** Verificar que el script de indexacion masiva procesa correctamente el PDF de la RESOLUCION N 058-2023-SUNASS-CD usando IDs deterministas UUIDv5.

**PDF procesado:** `RESOLUCION N_058-2023-SUNASS-CD-5-36.pdf`

**Resultado del script:**
```
INFO:__main__:Chunks indexados: 383
```

**Detalle:**
- Se extrajeron articulos del PDF usando `pdf_parser.py`
- Cada articulo fue dividido en numerales usando `legal_chunker.py`
- Se generaron 383 embeddings via Ollama (`nomic-embed-text`, dim=768)
- Se indexaron en Qdrant en lotes de 100 puntos
- Todos los IDs fueron calculados con `uuid5(NAMESPACE_DNS, "Reglamento Calidad Servicios Saneamiento|art:X|num:Y")`

**Resultado:** PASS - 383 chunks indexados exitosamente con IDs deterministas, sin duplicados.

---

## Resumen

| Prueba | Endpoint | Resultado | Observacion |
|--------|----------|-----------|-------------|
| 1 - Crear articulo | `POST /normativa/actualizar-articulo` | PASS | UUIDv5 determinista calculado correctamente |
| 2 - Upsert (sin duplicados) | `POST /normativa/actualizar-articulo` | PASS | Mismo ID, operacion ACTUALIZADO |
| 3 - Buscar articulo | `POST /normativa/buscar-articulo` | PASS | 1 resultado, texto actualizado |
| 4 - Eliminar articulo | `POST /normativa/eliminar-articulo` | PASS | Eliminado, verificacion: 0 resultados |
| 5 - Indexacion masiva PDF | `chunk_and_index.py` | PASS | 383 chunks indexados |

## Bugs corregidos durante las pruebas

1. **QDRANT_URL no configurado** en `docker-compose.yml` - el contenedor no podia alcanzar Qdrant
2. **Falta auto-creacion de coleccion** en el endpoint `actualizar-articulo`
3. **Ruta incorrecta de PDFs** en `chunk_and_index.py` - no encontraba el archivo en la ubicacion real
