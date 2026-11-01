# Diagnóstico de la búsqueda normativa (RAG) de Yumi

Revisión estática del backend y del frontend (2026-10-31) y mediciones en vivo contra el Qdrant de
desarrollo (`volumes/qdrant_storage`) con `nomic-embed-text` (Ollama). El gold son 30 casos con
etiquetas propuestas (ver "Límites"): las cifras son indicativas, no definitivas.

## Estado final

- **Orden de búsqueda:** primero `sunass_reclamos` (Reglamento de Reclamos, RCD 015-2023-SUNASS-CD) y,
  solo si nada supera el umbral o el LLM no puede argumentar con él, `sunass_reglamento` (Reglamento de
  Calidad, RCD 058-2023-SUNASS-CD). Lo fija `NORMATIVA_FUENTES` (el orden ES la prioridad) y vale para
  el agente de fundamentación, para `POST /normativa/busqueda` sin `coleccion` y para
  `POST /normativa/busqueda/escalonada`.
- **Colecciones vivas:** `sunass_reclamos` (98 puntos) y `sunass_reglamento` (276 puntos, reindexada con
  el chunker nuevo), ambas con `qwen3-embedding:0.6b` (1024 dimensiones).
- **Modelo y parámetros:** `OLLAMA_EMBEDDING_MODEL=qwen3-embedding:0.6b`, consulta con la instrucción
  `Instruct: Given a question about a water utility claim, retrieve the regulation article that answers it\nQuery: `
  y documentos sin prefijo; `NORMATIVA_TOP_K=3`, `NORMATIVA_UMBRAL_SCORE=0.58` (en el `.env` local y en
  `.env.example`). **Cada Ollama donde corra el backend necesita el modelo**
  (`ollama pull qwen3-embedding:0.6b`) y las dos colecciones reindexadas. Para volver a nomic: ver "Cómo revertir".
- **Ollama con GPU (opcional, solo local):** `make up-gpu` suma `docker-compose.gpu.yml`, que reserva la
  NVIDIA del equipo para el contenedor (RTX 3050, 100 % GPU según `ollama ps`). Indexar las dos normas pasó
  de ~2 min por corpus en CPU a 31 s (reclamos, incluida la carga del modelo) y 15 s (calidad). Es un archivo
  aparte porque quien no tenga GPU NVIDIA no podría levantar los contenedores con él.

## Fallos confirmados

| # | Dónde | Qué pasa | Efecto |
|---|-------|----------|--------|
| 1 | `legal_chunker.split_numerals` | El texto anterior al primer numeral (título del artículo + párrafo introductorio) se descarta. | En calidad, el Art. 93 pierde la definición de *promedio histórico*: dos casos del gold no se recuperan. |
| 2 | `legal_chunker.split_numerals` | El numeral se busca en cualquier parte del texto. Una referencia cruzada ("artículos 93.1 y 93.2") abre un chunk falso. | El índice anterior de calidad (266 puntos, ids aleatorios) conservaba esos fragmentos JUNTO a los numerales reales: 18 pares (artículo, numeral) repetidos y 13 puntos de menos de 40 caracteres (`"93.1 y"`, 6 caracteres). |
| 3 | `pdf_chunk.parse_document` | Parsea el índice como artículos y deja que el último artículo absorba disposiciones, anexos y formatos. | TUO de Reclamos: Art. 46 de 51 842 caracteres. La colección subida antes desde la UI (`reglamento_de_reclamos_2019__pdf`) tenía un chunk de **96 250 caracteres** (Art. 46). |
| 4 | `EmbeddingService` | `nomic-embed-text` sin los prefijos `search_query:` / `search_document:`. `.env.example` y README anunciaban BGE-M3, pero ningún código lo usaba. | **Medido**: con prefijos, reclamos MRR 0,775 → 0,875 y calidad hit@3 50 % → 62,5 % (mismo índice). |
| 5 | `EmbeddingService.dimension` | Fijo en 768. | Cambiar de modelo rompía el upsert con un error opaco. |
| 6 | `CONSULTA_POR_TIPO` | Faltaban 7 de 15 tipos de hallazgo (`fugas`, `atipico`, `equipo`, `mesesPromediados`, `rachaPromediados`, `mesesCortados`, `reclamosPrevios`). | La consulta de la inspección (caso de fugas) se armaba sin el concepto general. |
| 7 | `UMBRAL_SCORE = 0.5` | **Medido sin prefijos**: no filtraba nada (consulta absurda 0,62–0,77, correctas 0,70–0,84). | La decisión real la tomaba el LLM. Con prefijos sí aparece un hueco (ver "Umbral"). |
| 8 | Gold de informes históricos | Citan "Art. 88.3 (RCD 061-2018)". En el TUO 058-2023 esa regla es el **Art. 92.3**. | Un criterio "mismo número de artículo" daría falsos negativos; el gold se define por contenido. |
| 9 | `QdrantAdapter.create_collection` | Usaba siempre 768 e ignoraba `dim`, y no validaba la dimensión de una colección existente. | Desajustes solo visibles como error opaco de Qdrant. |
| 10 | Varios | `RecuperadorRAGAgent` sin clase base y sin ningún uso; `Retriever.build_context` sin ningún uso; `chunk_and_index.py` reindexaba con el chunker defectuoso al ejecutarlo como script; `test_pdf_chunk_pipeline` importaba un módulo inexistente; Makefile y README llamaban a `app.scripts.*` que no existe; README con marcadores de merge sin resolver. | Código muerto o roto. **Ya limpiado** (ver "Cambios hechos"). |

El frontend no renderiza los artículos recuperados (solo los guarda en el store), así que no es
la causa de fallos de búsqueda.

## Calidad: por qué "no buscaba bien"

Tres problemas sumados en el índice anterior de calidad (`sunass_reglamento`, 266 puntos):

1. **Texto roto**: 133 de 266 puntos con ligaturas rotas (`Veriﬁ cación`). La búsqueda por la palabra
   "notificación" daba 0 aciertos.
2. **Mal troceo**: 37 artículos sin encabezado ni párrafo inicial (entre ellos el 92, el 93 y el 107), 21
   fragmentos de referencias cruzadas como puntos aparte y chunks de hasta 7 539 caracteres.
3. **Modelo sin prefijos** (fallo 4).

`rag/calidad_chunker.py` + `rag/index_calidad.py` los resuelven: 276 chunks, los 137 artículos, 0
ligaturas rotas, 0 fragmentos, máximo 1 501 caracteres. Ahora viven en `sunass_reglamento` (la colección
anterior se reemplazó con `--recrear`).

Búsqueda por palabra clave (`/normativa/busqueda/palabra-clave`), aciertos índice anterior → nuevo:

| palabra | antes | ahora |
|---------|-------|-------|
| notificación | 0 | 7 |
| verificación | 2 | 23 |
| clasificación | 0 | 7 |
| modificación | 0 | 9 |
| oficina | 1 | 10 |
| diferencia de lecturas | 10 | 17 |

## Resultados medidos (Qdrant en vivo, mismo camino que Yumi)

`python -m app.test.rag.evaluar_busqueda --modo qdrant`

| Colección (30 casos) | hit@1 | hit@3 | hit@5 | MRR |
|----------------------|-------|-------|-------|-----|
| `sunass_reclamos` (TUO 2023, 98 chunks, qwen3-embedding:0.6b) | 85 % | **100 %** | 100 % | **0,917** |
| `sunass_reglamento` (calidad, chunker nuevo, qwen3-embedding:0.6b) | 75 % | **87,5 %** | 87,5 % | **0,792** |

Referencia, etapas anteriores con `nomic-embed-text`: reclamos sin prefijos 70 % / 85 % / 0,775 y con
prefijos 85 % / 90 % / 0,875; calidad con el índice anterior 50 % / 50 % / 0,518, con el chunker nuevo sin
prefijos 62,5 % / 75 % / 0,667 y con prefijos 62,5 % / 75 % / 0,713; la colección de reclamos de 2019
(subida desde la UI) 60 % / 80 % / 0,692.

- Los 3 casos de fuga de los informes históricos recuperan el Art. 92.3 de calidad en primer lugar.
- Único caso esperado que no entra al top-3: `consumo_excesivo_sin_fuga` (calidad), cuya etiqueta es
  dudosa: los informes históricos "sin indicios de fuga" no citan ningún artículo.
- top_k: con qwen3 reclamos ya llega al 100 % con k=3 y calidad no mejora con k=5. Se deja `NORMATIVA_TOP_K=3`.

### Comparación de modelos de embedding

Mismo corpus indexado (reclamos 98 chunks, calidad 276), mismas consultas, coseno en memoria; cada modelo
con el juego de prefijos que indica su ficha (`python -m app.test.rag.evaluar_busqueda --modo embeddings
--modelos nomic-embed-text,bge-m3,embeddinggemma,qwen3-embedding:0.6b --prefijos auto`):

| Modelo (dim.) | Reclamos hit@3 / MRR | Calidad hit@3 / MRR | Acierto mínimo vs ruido máximo (reclamos · calidad) |
|---------------|----------------------|---------------------|------------------------------------------------------|
| nomic-embed-text (768) con prefijos | 90 % / 0,875 | 75 % / 0,713 | 0,714 vs 0,692 · 0,764 vs 0,759 |
| bge-m3 (1024) | 90 % / 0,887 | 75 % / 0,738 (hit@5 100 %) | 0,654 vs 0,503 · 0,666 vs 0,561 |
| embeddinggemma (768) con prompts | 95 % / 0,867 | 75 % / 0,797 | 0,511 vs 0,373 · 0,480 vs 0,443 |
| **qwen3-embedding:0.6b (1024) con instrucción** | **100 % / 0,917** | **87,5 % / 0,792** | 0,609 vs 0,487 · 0,667 vs 0,565 |

- qwen3 es el mejor en hit@3 en las dos normas y en MRR de reclamos, y casi empata el mejor MRR de calidad
  (0,797 de embeddinggemma). Sin su instrucción baja a 95 % / 0,910 y 75 % / 0,719: la instrucción ayuda,
  pero sin ella sigue por encima de nomic en reclamos. La instrucción se escribió antes de medir y no se
  ajustó después.
- **La ventaja en ranking es pequeña, no concluyente**: comparado caso por caso con nomic (28 casos con
  artículo esperado) qwen3 gana en 5, nomic gana en 5 y 18 empatan. qwen3 recupera dentro del top-3 los
  dos casos de reclamos que nomic perdía y `racha_promediados`; nomic lo supera en el puesto exacto de varios
  casos (2º o 3º en vez de 1º).
- **La ventaja grande es la separación de scores**: con nomic el hueco entre acierto y ruido es de 0,022
  (reclamos) y 0,005 (calidad), prácticamente inusable; con qwen3 es de 0,122 y 0,102.
- Costo: 639 MB en disco y vectores de 1024 dimensiones, contra 274 MB y 768. Con GPU la diferencia en
  tiempo de indexado es despreciable.
- n es chico (20 + 8 casos): conviene repetir la comparación cuando EMAPA valide el gold.

### Qué mejora la búsqueda (comparación en memoria, `nomic-embed-text`)

Reclamos, MRR (hit@3 entre paréntesis):

| Texto que se vectoriza | sin prefijos | con prefijos nomic |
|------------------------|--------------|--------------------|
| norma + título + capítulo + artículo + texto (mi primera versión) | 0,690 (75 %) | 0,682 (80 %) |
| artículo + texto | 0,637 (75 %) | 0,810 (80 %) |
| **solo el cuerpo del numeral** (lo que se indexa) | 0,775 (85 %) | **0,875 (90 %)** |

- Anteponer el título y el capítulo **empeoró** la búsqueda: se repite en todos los numerales del
  artículo y los vuelve casi indistinguibles.
- Excluir los anexos **no mejora** el resto de los casos y pierde los 2 que esperan el Anexo 3.

### Umbral y escalada

Con `nomic-embed-text` sin prefijos no había umbral que separara (calidad ni siquiera tenía hueco) y con
prefijos el hueco era de 0,022 y 0,005. Con `qwen3-embedding:0.6b` los scores se reparten mucho más:

- reclamos: aciertos top-1 con mínimo 0,609 (mediana 0,706); consultas ajenas hasta 0,487;
- calidad: aciertos con mínimo 0,667 (mediana 0,733); consulta ajena hasta 0,565.

`NORMATIVA_UMBRAL_SCORE=0.58` queda entre ambos. Se probó 0,50 primero y era demasiado justo: el Anexo 2
de reclamos salía en 0,4965 para una consulta de fugas y una consulta absurda se colaba en calidad
(Art. 102 en 0,54). A 0,58 el 100 % de los aciertos sigue en el puesto 1 y en reclamos se pierde un artículo
secundario del top-3 (recall@3 95 % en vez de 100 %). Los "falsos positivos" de la tabla (60–80 %) son casos
cuya respuesta está en la OTRA norma o en ninguna y que igual superan el umbral: esa barrera sigue siendo el
LLM (`aplica=false` → se escala). Hay poca evidencia de negativos (2 casos absurdos) y las consultas
conversacionales sueltas pueden caer cerca del umbral (una sobre notificación y apelación sacó 0,60), así que
conviene recalibrar con consultas reales.

Verificación del orden contra la API en vivo (`POST /normativa/busqueda/escalonada`, umbral 0,58):

| consulta | nivel 0 `sunass_reclamos` | nivel 1 `sunass_reglamento` | se elige |
|----------|---------------------------|------------------------------|----------|
| medidor sobrerregistra + verificación posterior | supera (15.1 en 0,71) | supera | **reclamos** |
| fuga no visible reparada, consumo sobre promedio histórico | no supera (Anexo 2, 0,50) | supera (92.3 en 0,64) | **calidad** |
| préstamo bancario con tasa de interés | no supera (0,46) | no supera (0,54) | ninguna |

## Cambios hechos

- **Colección `sunass_reclamos`**: `rag/reclamos_chunker.py` (46 artículos por numeral, 3
  disposiciones, Anexo 2 y Anexo 3 §1) + `rag/index_reclamos.py` (`--dry-run`, `--recrear`). El PDF
  está en `storage/files/reclamos/`.
- **Colección `sunass_reglamento`**: `rag/calidad_chunker.py` + `rag/index_calidad.py` (mismas opciones).
  `index_reclamos.indexar_chunks` es el indexador genérico compartido.
- **Búsqueda escalonada** (`rag/normativa_escalonada.py` + `FundamentacionNormativaAgent`): primero
  `sunass_reclamos`; si el LLM no puede argumentar, o nada supera el umbral, pasa a
  `sunass_reglamento`. Si una colección no existe, se omite. Cada artículo lleva `coleccion` y
  `norma_corta`; `base_legal` indica la norma. Config: `NORMATIVA_FUENTES`, `NORMATIVA_UMBRAL_SCORE`,
  `NORMATIVA_TOP_K`.
- `EmbeddingService`: modelo desde `settings`, dimensión detectada, prefijos configurables, indexado
  por lotes. `QdrantAdapter`: validación de dimensión y `delete_collection`.
- **Endpoints**: `POST /normativa/busqueda` sin `coleccion` ahora busca por niveles (reclamos →
  calidad) y cada resultado indica su `coleccion`; con `coleccion` consulta solo esa.
  `POST /normativa/busqueda/escalonada` (sin LLM: top-k y score por norma y cuál se elegiría).
  `POST /normativa/documentos/pdf` acepta `estructura` = `auto` (por defecto: `sunass_reclamos` →
  chunker de reclamos, `sunass_reglamento` → chunker de calidad, otra colección → genérico),
  `reclamos_tuo`, `calidad_tuo` o `generica`. Así subir los PDF desde la UI ya no recrea el troceo roto.
- Frontend: `useFlujoTareas.ts` reemplaza los artículos al llegar `fundamentacion`. No se probó en el
  navegador.
- **Limpieza**: eliminados `agents/recuperador_rag.py` (roto y sin uso), `Retriever.build_context` y sus
  dos auxiliares (sin uso), el bloque `__main__` de `chunk_and_index.py` (reindexaba calidad con el
  chunker defectuoso; `build_index` queda para la carga genérica de la UI), la línea muerta
  `EMBEDDING_MODEL=BAAI/bge-m3` de `.env.example`, la constante `COLECCION_CALIDAD_V2` y el alias
  `sunass_reglamento_v2`. Corregidos el import roto de `test_pdf_chunk_pipeline`, los comandos
  `app.scripts.*` inexistentes del Makefile (`make index`) y del README, y resueltos los marcadores de
  merge del README (la otra mitad estaba vacía).
- **Integración con `origin/main`** (flujo nuevo de fundamentación: el LLM elige los 1–3 problemas
  determinantes, `marcar_aplica` marca qué artículos regulan cada uno y se redacta un párrafo):
  - `FundamentacionNormativaAgent.buscar_y_marcar` hace la búsqueda escalonada dentro de ese flujo: artículos
    de reclamos + `marcar_aplica`; si ninguno aplica, también los de calidad. `fundamentacion_service` lo usa
    y cada artículo lleva `coleccion` y `norma_corta`; los prompts de `marcar_aplica` y `redactar_parrafo`
    ya no dicen "Reglamento de Calidad" a secas.
  - Consultas de reclamos para los tipos nuevos de hallazgo (`fugaNoVisible`, `fugaVisible`, `descensoConsumo`…).
  - `normalizar_numero_articulo("ANEXO 3")` devolvía `"3"`: editar o desactivar el Art. 3 de reclamos habría
    arrastrado el Anexo 3. Ahora anexos, disposiciones y formatos conservan su etiqueta.
  - La reconstrucción (`/normativa/reglamento/reconstruccion`) marcaba 14 falsas inconsistencias en calidad
    (preámbulos y partes de un numeral largo) y 16 en reclamos (anexos leídos como artículos); ahora 0 en las dos.
  - Altas y ediciones sueltas (`/normativa/articulos`, carga de Markdown, indexado genérico) calculan el vector
    con el prefijo de documento (`EmbeddingService.encode_document`), igual que el indexado de las dos normas.
  - `docker-compose.override.yml` ya no existe en `main` (se movió a `docker-compose.dev.yml` y `.prod.yml`):
    `make up` usa el de desarrollo y `make up-gpu` suma `docker-compose.gpu.yml`.
- Tests offline (49) en `test_reclamos_chunker.py`, `test_calidad_chunker.py`, `test_normativa_escalonada.py`
  y `test_integracion_normativa.py`. `main` eliminó `test_qdrant_adapter.py` y la carpeta `app/test/informes`.
- Evaluación: `app/test/rag/evaluar_busqueda.py` (`--modo lexico|embeddings|qdrant`) +
  `gold_busqueda.json`.

## Siguiente

1. ~~Borrar las colecciones sobrantes~~ **Hecho** a pedido del usuario: `reglamento_de_reclamos_2019__pdf`
   (versión anterior de la norma, con el chunk gigante) y `sunass_reglamento_v2` (copia sin prefijos de
   `sunass_reglamento`). Quedan solo `sunass_reclamos` y `sunass_reglamento`.
2. ~~Comparar otros modelos~~ **Hecho** (ver "Comparación de modelos de embedding"). Quedan descargados en
   el Ollama local `bge-m3`, `embeddinggemma` y `qwen3-embedding:0.6b`; los dos primeros pueden quitarse con
   `docker exec ollama ollama rm <modelo>` si no se van a usar.
   **Para desplegar**: `ollama pull qwen3-embedding:0.6b` en el Ollama del servidor, mismas variables del
   `.env.example` y reindexar las dos colecciones allí (`make index`).
3. Probar el flujo completo con un LLM real y un token EMAPA (no se hizo) y revisar el frontend en el
   navegador.
4. Validar el gold con quien atiende reclamos y sumar más casos negativos para recalibrar el umbral.

## Límites

- 30 casos, solo 2 de ellos fuera de ámbito; las etiquetas son propuestas mías y hay que validarlas
  con quien atiende reclamos. Una está marcada como dudosa en el propio JSON.
- Anexo 3 §2-§3 y Anexo 1 no se indexan (tablas de varias columnas; el Anexo 1 ya existe como
  `anexo1_tipos_reclamo` en otros entornos). Anexo 4 y Formatos: sin texto útil. El PDF de calidad del
  repo no trae anexos.
- La instrucción de consulta y el umbral de 0,58 están calibrados para `qwen3-embedding:0.6b`; otro modelo
  exige reindexar y recalibrar.
- **Cómo revertir a nomic**: en `.env`, `OLLAMA_EMBEDDING_MODEL=nomic-embed-text`,
  `EMBEDDING_QUERY_PREFIX="search_query: "`, `EMBEDDING_DOCUMENT_PREFIX="search_document: "`,
  `NORMATIVA_UMBRAL_SCORE=0.70`, y reindexar las dos colecciones (`make index`, ~45 s con GPU).
- Los scripts `app/test/debug_*.py` importan `rag.qdrant_store` (módulo inexistente) y consultan la
  colección `anexo1_tipos_reclamo`: están rotos desde antes, no se tocaron por ser del clasificador.
