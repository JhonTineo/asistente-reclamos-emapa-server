# Cambios en la búsqueda normativa de Yumi: qué fallaba, qué se corrigió y por qué es mejor

Este documento explica, en lenguaje llano y con la evidencia medida, los cambios hechos al RAG de
normativa del asistente de reclamos (backend `asistente-reclamos-emapa-server`). El registro técnico
completo, con todas las tablas, está en [DIAGNOSTICO_RAG.md](DIAGNOSTICO_RAG.md); aquí se cuenta la historia
y se argumenta cada decisión.

> **Alcance de las cifras.** Se midieron con un conjunto de 30 casos (`app/test/rag/gold_busqueda.json`)
> cuyas etiquetas propuse yo a partir de la norma y de informes históricos. Son indicativas, no definitivas:
> falta que EMAPA las valide (ver "Límites").

---

## 1. Qué se pidió

1. Definir los parámetros que dan búsquedas precisas (cuántos artículos traer, a partir de qué puntaje).
2. Evaluar modelos de embeddings y quedarse con el que mejor resultado dé.
3. Asegurar que la búsqueda recupere, como mínimo, los artículos que se usaron en reclamos anteriores.
4. Crear la colección del **Reglamento de Reclamos** (RCD 015-2023-SUNASS-CD) y consultarla **primero**; pasar al
   **Reglamento de Calidad** (RCD 058-2023-SUNASS-CD) solo si con la primera no se puede argumentar.
5. Borrar lo que ya no se usa.

## 2. Resumen en una tabla

Medido contra Qdrant en vivo, con el mismo camino de consulta que usa Yumi:

| | Antes | Ahora |
|---|---|---|
| Norma de reclamos | No había colección vigente (solo una versión anterior subida desde la UI, hit@3 80 %, con un chunk de 96 250 caracteres) | `sunass_reclamos`, 98 chunks, **hit@3 100 %**, MRR **0,917** |
| Norma de calidad | hit@3 **50 %**, MRR 0,518 | hit@3 **87,5 %**, MRR **0,792** |
| Puntos de calidad con texto roto (ligaturas) | 133 de 266 | **0** de 276 |
| Búsqueda por la palabra "notificación" en calidad | **0** aciertos | 7 aciertos |
| Orden de consulta | Solo calidad | Reclamos primero, calidad como respaldo |
| Umbral de puntaje | 0,5: no filtraba nada | 0,58: separa acierto de ruido |
| Indexar las dos normas | ~2 min por corpus (CPU) | 15–31 s (GPU) |
| Tests automáticos de chunking y búsqueda escalonada | ninguno | 33 nuevos (34 con el del adaptador Qdrant) |

---

## 3. Fallas que se encontraron y cómo se corrigieron

### A. Los datos que se indexaban estaban dañados

**A1. Palabras rotas por ligaturas.** El PDF de El Peruano guarda "fi", "fl"… como un solo carácter especial
(ﬁ). Al extraer el texto quedaba `Veriﬁ cación`, con un espacio suelto.
- *Evidencia:* 133 de los 266 puntos de calidad tenían ligaturas rotas; buscar "notificación" daba **0 aciertos**
  y "clasificación", "modificación" también 0.
- *Corrección:* el extractor repara las ligaturas (sin normalización Unicode general, que habría convertido
  "Nº" en "No"). Hoy: 0 puntos con ligaturas y la búsqueda de "notificación" encuentra 7.

**A2. Se perdía el encabezado y el párrafo inicial de los artículos.** El troceador descartaba todo lo que
había antes del primer numeral.
- *Evidencia:* 37 de 134 artículos quedaron sin su título ni su introducción, entre ellos el 92 (fugas),
  el 93 y el 107. Del Art. 93 se perdió la definición de *Promedio Histórico de Consumos*, necesaria para
  fundamentar reclamos por consumo.
- *Corrección:* el encabezado y el preámbulo ahora son un chunk propio y cada numeral hereda su artículo.
  Los 137 artículos de calidad tienen encabezado.

**A3. Referencias cruzadas que se confundían con numerales.** Una frase como "…los numerales 93.1 y 93.2…"
abría un chunk falso que empezaba en "93.1 y".
- *Evidencia:* 21 fragmentos espurios, 13 puntos de menos de 40 caracteres (uno de 6) y 18 pares
  artículo/numeral duplicados. En la colección vieja de reclamos, el fragmento "14.2, pese a haber sido…"
  **pisó el texto real del 14.2** porque compartían identificador.
- *Corrección:* un numeral solo se reconoce al inicio de un bloque del PDF y solo si su primer número es el del
  artículo en curso. Las referencias cruzadas se pegan al párrafo al que pertenecen.

**A4. Chunks gigantes.** El último artículo absorbía las disposiciones, anexos y formatos que venían después.
- *Evidencia:* chunk de **7 539** caracteres en calidad (Art. 137), de **51 842** en el TUO de reclamos
  (Art. 46) y de **96 250** en la colección de reclamos subida antes. Un vector no puede representar bien
  decenas de miles de caracteres.
- *Corrección:* cada numeral es un chunk; las disposiciones y los anexos se separan; lo largo se parte por
  párrafos con tope de 1 500 (calidad) y 2 200 (reclamos) caracteres.

**A5. El índice del documento se leía como si fueran artículos.** El troceador genérico trataba la tabla de
contenido como artículos reales (en la colección vieja de reclamos, 13 chunks eran solo títulos del índice).
- *Corrección:* se excluye la tabla de contenido y la resolución de aprobación; cada norma tiene su chunker
  (`reclamos_chunker.py`, `calidad_chunker.py`) que entiende sus dos columnas, "Art. 126.-" frente a
  "Artículo 126.-", subcapítulos y disposiciones con ordinales.

**A6. Identificadores.** El índice de calidad tenía ids aleatorios (0 de 266 coincidían con el esquema
determinista del código), así que reindexar habría duplicado todo, y con el esquema determinista los
fragmentos falsos se habrían pisado entre sí.
- *Corrección:* id determinista por artículo y numeral (más `#pN` en las partes de un chunk largo). Reindexar es
  idempotente y los chunks se validan antes de gastar embeddings (ids únicos, tamaños, los 46 y 137 artículos).

### B. Cómo se vectorizaba

**B1. Faltaban los prefijos de tarea.** Los modelos de embeddings modernos esperan una marca distinta para
consultas y para documentos; el servicio no la enviaba.
- *Evidencia:* con nomic, ponerlos subió el MRR de reclamos de 0,775 a 0,875 y el hit@3 de calidad de 50 % a
  62,5 % sobre el mismo índice. Ahora son configurables (`EMBEDDING_QUERY_PREFIX`/`EMBEDDING_DOCUMENT_PREFIX`).

**B2. Se vectorizaba texto de más.** La primera versión anteponía norma, título y capítulo a cada numeral.
- *Evidencia:* ese texto se repite en todos los numerales de un artículo y los vuelve casi indistinguibles:
  MRR 0,690 contra 0,775 al vectorizar **solo el cuerpo del numeral**. Se cambió a solo cuerpo; el título y el
  capítulo siguen guardados como datos para mostrar y citar.

**B3. Dimensión fija en 768.** `EmbeddingService.dimension` devolvía siempre 768 y `create_collection` ignoraba
la dimensión pedida; cambiar de modelo fallaba con un error opaco de Qdrant.
- *Corrección:* la dimensión se detecta consultando al modelo, y `QdrantAdapter` valida la dimensión de una
  colección existente con un mensaje claro. Por eso pudo pasarse de 768 (nomic) a 1024 (qwen3).

**B4. Documentación que mentía.** `.env.example` y el README anunciaban BGE-M3, pero ningún código lo usaba (el
modelo real era `nomic-embed-text`). Se corrigió la documentación y se eliminó la variable muerta.

### C. Cómo se buscaba y cuándo se confiaba

**C1. Solo se consultaba la norma de calidad.** No existía la colección del Reglamento de Reclamos, que es la
que debe usarse primero. Se creó `sunass_reclamos` (ver sección 4).

**C2. El umbral de 0,5 no filtraba nada.**
- *Evidencia:* con nomic, una consulta absurda ("préstamo bancario") sacaba 0,62–0,77 de similitud y las
  correctas 0,70–0,84. Con 0,5, el 100 % de las consultas "pasaba" y quien decidía de verdad era el LLM.
- *Corrección:* se eligió un modelo que separa mejor (ver D) y se calibró un umbral con datos (0,58).
  El umbral sigue siendo una perilla (`NORMATIVA_UMBRAL_SCORE`), no el criterio de escalada.

**C3. Consultas incompletas.** `CONSULTA_POR_TIPO` no tenía 7 de los 15 tipos de hallazgo (`fugas`, `atipico`,
`equipo`, `mesesPromediados`, `rachaPromediados`, `mesesCortados`, `reclamosPrevios`), así que la inspección
de fugas se buscaba sin el concepto general. Se completaron y se agregó un juego de consultas para la norma de
reclamos, que "habla" de procedimiento y no de facturación.

**C4. El criterio de comparación con informes históricos era engañoso.** Los informes anteriores citan
"Art. 88.3 (RCD 061-2018)"; en el TUO 058-2023 esa misma regla (fugas no visibles y promedio histórico) es el
**Art. 92.3**. Comparar por número de artículo habría dado falsos negativos, así que el gold se define por
contenido. Los tres casos de fuga del gold recuperan el Art. 92.3 en primer lugar.

### D. Código, operación y rendimiento

- **Subida de PDF desde la UI:** usaba siempre el troceador defectuoso y por eso se había generado la colección
  vieja de reclamos. El endpoint ahora acepta `estructura=auto` (por defecto): la colección `sunass_reclamos` o
  `sunass_reglamento` usa su chunker propio, cualquier otra usa el genérico.
- **Código muerto o roto, eliminado o arreglado:** `RecuperadorRAGAgent` (sin clase base y sin ningún uso),
  `Retriever.build_context` y sus dos auxiliares (sin uso), el bloque que ejecutaba `chunk_and_index.py` como
  script (reindexaba calidad con el troceador defectuoso), el import roto de `test_pdf_chunk_pipeline`,
  comandos `app.scripts.*` inexistentes en el Makefile y el README, y los marcadores de merge del README.
- **Rendimiento:** Ollama corría 100 % en CPU dentro de Docker aunque la máquina tiene una RTX 3050. Se reservó la
  GPU en `docker-compose.override.yml` (solo local): indexar bajó de unos 2 minutos por corpus a 15–31 s.

---

## 4. Lo que se construyó

### Búsqueda escalonada (reclamos primero, calidad después)

```
Hallazgo ─► consulta redactada para cada norma
              │
              ▼
      1) sunass_reclamos  ── ¿algún artículo con puntaje ≥ umbral?
              │ sí                              │ no
              ▼                                 │
   El LLM decide si aplica ── aplica ─► cita "Art. X del Reglamento de Reclamos"
              │ no aplica / no determinable     │
              └──────────────► 2) sunass_reglamento ─► igual, cita "… del Reglamento de Calidad"
                                                        │ nada supera el umbral
                                                        ▼
                                                  sin base normativa
```

- **Por qué la decisión final la toma el LLM y no el puntaje:** ningún umbral separa limpiamente "este artículo
  aplica" de "este artículo habla de algo parecido". Por ejemplo, los chunks del Anexo 3 de reclamos atraen
  casi cualquier consulta de hallazgo. Por eso el modelo puede responder `aplica=false` y entonces se escala a
  calidad. El umbral solo descarta lo claramente irrelevante.
- Cada artículo devuelto lleva `coleccion` y `norma_corta`, y la conclusión cita "Art. 15.5 del Reglamento de
  Reclamos" o "Art. 92.3 del Reglamento de Calidad" sin ambigüedad.
- El orden lo fija `NORMATIVA_FUENTES=sunass_reclamos,sunass_reglamento`: el orden *es* la prioridad. Si una
  colección no existe, se omite sin romper nada.
- `POST /normativa/busqueda` sin `coleccion` busca por niveles; `POST /normativa/busqueda/escalonada` muestra, sin
  usar el LLM, el top-k y el puntaje de cada norma y cuál se elegiría (sirve para calibrar).

Comprobación en vivo contra la API:

| Consulta | Reclamos | Calidad | Se elige |
|---|---|---|---|
| Medidor sobrerregistra y verificación posterior | supera (Art. 15.1, 0,71) | supera | **reclamos** |
| Fuga no visible reparada, consumo sobre el promedio histórico | no supera (0,50) | supera (Art. 92.3, 0,64) | **calidad** |
| Préstamo bancario con tasa de interés | no supera (0,46) | no supera (0,54) | ninguna |

### Las dos colecciones

| Colección | Norma | Chunks | Cómo se llena |
|---|---|---|---|
| `sunass_reclamos` | TUO Reglamento General de Reclamos (RCD 015-2023) | 98: 46 numerales, 33 artículos, 2 preámbulos, 3 disposiciones, 14 de anexos | `index_reclamos` |
| `sunass_reglamento` | TUO Reglamento de Calidad (RCD 058-2023) | 276: 142 numerales, 112 artículos, 6 preámbulos, 16 disposiciones | `index_calidad` |

Los anexos 1 y 3 §2–§3 (tablas de varias columnas) no se indexan; el PDF de calidad del repo no trae anexos.

---

## 5. Por qué el modelo `qwen3-embedding:0.6b`

Se compararon cuatro modelos con el mismo corpus indexado y las mismas 30 consultas, cada uno con el juego de
prefijos que indica su ficha:

| Modelo | Reclamos hit@3 / MRR | Calidad hit@3 / MRR | Hueco acierto vs. ruido (reclamos · calidad) |
|---|---|---|---|
| nomic-embed-text (con prefijos) | 90 % / 0,875 | 75 % / 0,713 | 0,022 · 0,005 |
| bge-m3 | 90 % / 0,887 | 75 % / 0,738 | 0,151 · 0,105 |
| embeddinggemma | 95 % / 0,867 | 75 % / 0,797 | 0,138 · 0,037 |
| **qwen3-embedding:0.6b** | **100 % / 0,917** | **87,5 % / 0,792** | 0,122 · 0,102 |

**Argumento honesto.** En ranking exacto la ventaja sobre nomic es pequeña: caso por caso (28 con artículo
esperado) qwen3 gana en 5, nomic en 5 y 18 empatan. Lo que inclinó la decisión fue:

1. **Recupera más dentro del top-3**, que es lo que realmente lee el LLM: trae los dos casos de reclamos y el de
   `racha_promediados` que nomic no traía.
2. **Separa mucho mejor el acierto del ruido** (hueco de 0,12 y 0,10 contra 0,02 y 0,005). Con nomic el umbral era
   prácticamente inusable; con qwen3 funciona con margen.

Costo: 639 MB en disco y vectores de 1024 dimensiones (nomic: 274 MB y 768). Con GPU es despreciable. La decisión
es reversible: en `DIAGNOSTICO_RAG.md` está el paso a paso para volver a nomic.

## 6. Parámetros óptimos (objetivo 1)

| Parámetro | Valor | Por qué |
|---|---|---|
| `NORMATIVA_TOP_K` | 3 | Reclamos ya llega a 100 % con k=3; calidad no mejora con k=5 con qwen3. Más artículos solo gastan contexto del LLM. |
| `NORMATIVA_UMBRAL_SCORE` | 0,58 | Los aciertos puntúan ≥ 0,609 y el ruido llega a 0,565. Con 0,50 una consulta absurda se colaba en calidad (Art. 102, 0,54) y el Anexo 2 salía en 0,4965, demasiado cerca. A 0,58 todos los aciertos siguen en el puesto 1; el costo es perder un artículo secundario del top-3 de reclamos (recall@3 95 %). |
| Texto vectorizado | solo el cuerpo del numeral | Ver B2. |
| Prefijo de consulta | instrucción de qwen3 | Sin ella baja a 95 %/0,910 en reclamos y 75 %/0,719 en calidad. Se escribió antes de medir y no se ajustó. |
| Prefijo de documento | ninguno | Es lo que indica la ficha de qwen3. |

## 7. Los artículos de reclamos anteriores (objetivo 3)

- Los tres casos de fuga de los informes históricos recuperan el **Art. 92.3** de calidad en primer lugar.
- De los 30 casos, el único con artículo esperado que no entra al top-3 es `consumo_excesivo_sin_fuga`, cuya
  etiqueta es dudosa: los informes "sin indicios de fuga" no citan ningún artículo.
- Los informes históricos citan la numeración del reglamento de 2018; por eso el gold compara por contenido y no
  por número (ver C4).

---

## 8. Cómo se probó

- **34 tests offline** (sin Ollama ni Qdrant): las fallas de datos (A1–A6) tienen su prueba (ligaturas, preámbulo
  del Art. 93, numerales únicos, 137 y 46 artículos, tamaños, ids únicos) y también el orden de la búsqueda
  escalonada, la escalada cuando el LLM abstiene y las colecciones ausentes. Las demás correcciones (umbral,
  modelo, GPU, endpoints) se comprobaron con el arnés y contra la API en vivo, no con tests automáticos.
- **Arnés de evaluación** (`app/test/rag/evaluar_busqueda.py`): hit@k, recall@k, MRR, curva de umbrales,
  comparación de modelos y línea base léxica (BM25). Modos: `lexico`, `embeddings` y `qdrant` (colecciones en vivo,
  como lo hace la app).
- **API en vivo:** búsquedas escalonadas, búsqueda por palabra clave y carga de PDF contra el Qdrant local.

```bash
python -m app.test.rag.evaluar_busqueda --modo qdrant
python -m app.test.rag.evaluar_busqueda --modo embeddings --modelos nomic-embed-text,bge-m3,embeddinggemma,qwen3-embedding:0.6b
python -m pytest app/test/test_reclamos_chunker.py app/test/test_calidad_chunker.py app/test/test_normativa_escalonada.py app/test/test_qdrant_adapter.py
```

## 9. Qué se borró

- Colecciones de Qdrant: el índice viejo de calidad (reemplazado en el mismo nombre), `reglamento_de_reclamos_2019__pdf`
  (versión anterior del reglamento, con el chunk de 96 250 caracteres) y `sunass_reglamento_v2` (copia sin prefijos).
- Código: `recuperador_rag.py`, `Retriever.build_context` y auxiliares, el `__main__` de `chunk_and_index.py`, la
  constante y el alias `v2`, la variable muerta `EMBEDDING_MODEL`.
- Se **conservaron** los modelos `bge-m3` y `embeddinggemma` descargados en el Ollama local (ocupan ~1,8 GB y se
  quitan con `ollama rm`).

## 10. Límites y pendientes

- **Gold:** 30 casos con etiquetas mías, solo 2 negativos absurdos; falta validarlas con quien atiende reclamos y
  sumar más negativos para recalibrar el umbral. Las consultas conversacionales sueltas pueden caer cerca de 0,58.
- **No probado:** el flujo completo con un LLM real y el token de EMAPA, ni el frontend en el navegador. El cambio
  de frontend (reemplazar los artículos al llegar el evento `fundamentacion`) es mínimo pero no se vio en pantalla.
- **Despliegue:** el servidor necesita `ollama pull qwen3-embedding:0.6b` y reindexar allí las dos colecciones
  (`make index`). Nada se tocó fuera de la máquina local.
- **Sin cubrir:** Anexo 1 y Anexo 3 §2–§3 de reclamos, y los anexos de calidad (no vienen en el PDF del repo).
- Los scripts `app/test/debug_*.py` están rotos desde antes (importan un módulo que no existe) y no se tocaron.
- No hay nada confirmado en git.

## 11. Cómo operar

```bash
# Con Docker Desktop abierto
docker compose up qdrant ollama -d
docker exec ollama ollama pull qwen3-embedding:0.6b

# Crear/recrear las dos colecciones (usa los prefijos y el modelo del .env)
make index
# o por separado:
python -m app.src.application.services.rag.index_reclamos --recrear
python -m app.src.application.services.rag.index_calidad --recrear

# Revisar los chunks sin red ni embeddings
python -m app.src.application.services.rag.index_reclamos --dry-run
python -m app.src.application.services.rag.index_calidad --dry-run
```

Si se cambia el modelo o los prefijos hay que **reindexar las dos colecciones y recalibrar el umbral**: los vectores
de modelos distintos no se pueden comparar entre sí.

## 12. Archivos

**Nuevos:** `rag/reclamos_chunker.py`, `rag/calidad_chunker.py`, `rag/index_reclamos.py`, `rag/index_calidad.py`,
`rag/normativa_escalonada.py`, `app/test/test_reclamos_chunker.py`, `test_calidad_chunker.py`,
`test_normativa_escalonada.py`, `app/test/rag/` (arnés y gold), `app/src/storage/files/reclamos/` (PDF del TUO de
reclamos), `DIAGNOSTICO_RAG.md`, este documento.

**Modificados:** `embeddings.py`, `retriever.py`, `qdrant_adapter.py`, `vector_db_port.py`, `settings.py`,
`fundamentacion_normativa.py`, `conclusion.py`, `investigacion_stream.py`, `normativa_busqueda.py`,
`normativa_documentos.py`, `schemas/normativa.py`, `chunk_and_index.py`, `docker-compose.override.yml`,
`.env.example`, `Makefile`, `README.md`, `test_pdf_chunk_pipeline.py`; en el frontend `useFlujoTareas.ts` y
`reclamosStore.tsx`.

**Eliminado:** `usecase/agents/recuperador_rag.py`.
