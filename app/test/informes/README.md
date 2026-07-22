# Harness de evaluación del Informe de Atención

Compara los **informes de atención reales** (10 PDFs históricos hechos por el
personal) contra los que **genera la herramienta**, para medir qué tan bien
reproduce el resultado y dónde falla.

## Idea general

El veredicto de la herramienta NO lo decide libremente el LLM: es una puerta
lógica sobre los objetivos de investigación (ver `agents/conclusion.py`). Por eso
el test mide en **varios niveles**, no solo el FUNDADO/INFUNDADO final:

| Nivel | Indicador | Qué detecta |
|-------|-----------|-------------|
| Veredicto | FUNDADO/INFUNDADO real vs generado (matriz de confusión) | Indicador principal |
| Objetivos | ¿los objetivos generados cubren los puntos que investigó el real? | objetivo faltante/sobrante que voltea el veredicto |
| Por medio | precision/recall de **hechos** (lectura, inodoros, fugas…) real vs `entidad` EMAPA | pérdida/invención de datos en el preprocesamiento |
| Por medio | LLM-judge del **resumen** generado vs descripción real | fidelidad, cobertura, alucinación en la redacción |
| Conclusión | LLM-judge del **razonamiento** (base legal Art. 88.3, lógica de facturación) | calidad normativa más allá del binario |
| Estabilidad | correr el mismo caso 2-3 veces | varianza entre corridas (hay ~4 llamadas LLM encadenadas) |

Solo se comparan los **medios que el informe real sí analizó**. Los medios extra
que la herramienta analiza se registran aparte (si uno de ellos voltea el
veredicto, es un hallazgo).

## Flujo de trabajo (3 etapas)

### 1. Extraer el "gold" (borrador automático) — LISTO

```bash
python -m app.test.informes.extraer_gold \
    --pdf-dir "D:/JhonTineo/Desktop/test_informe" \
    --out-dir app/test/informes/gold
```

Segmenta cada PDF en: header (numero, codreclamo, suministro), puntos numerados
(cada uno con `medio_sugerido`), conclusión y veredicto. La cita literal del
Art. 88.3 SUNASS (boilerplate) se aísla en el punto `analisis_normativo` para
que no contamine la comparación de descripciones.

### 2. Confirmar el gold — TÚ (revisión humana)

En cada `gold/*.json`, por cada punto:
- **Confirma `medio_id`**: mapea el punto al medio de la herramienta
  (`inspeccion_externa`, `inspeccion_interna`, `record_facturacion`,
  `tarjeta_lectura`, `corte_reapertura`, `saldo_detalle`). Deja `null` en el
  punto `analisis_normativo` (no es un medio; alimenta la conclusión).
- **Llena `hechos`**: los datos estructurados que afirma la descripción real,
  para comparar objetivamente contra los datos de EMAPA. Esquema sugerido:

```jsonc
// inspeccion_externa
{ "medidor_operativo": true, "lectura_m3": 2052, "tipo_predio": "alquiler 11 hab", "fuga_no_visible": true }
// inspeccion_interna
{ "inodoros": 6, "lavatorios": 6, "duchas": 6, "grifos": 2, "estado": "buen estado", "fugas": false }
// record_facturacion
{ "categoria": "comercial", "meses_reclamados": ["noviembre"] }
```

- Completa `codsede`, `codsuc`, `codcliente` (normalmente `codcliente` = suministro;
  `codsede`/`codsuc` son fijos de EMAPA San Martín — confirmarlos).
- Pon `_revisado_por_humano: true` cuando termines cada archivo.

### 3a. Regenerar con la herramienta (runner) — LISTO

Requiere la API corriendo y un token EMAPA vigente (header Authorization).

```bash
# Token: cópialo del sistema EMAPA (con o sin el prefijo "Bearer ").
export EMAPA_TOKEN="Bearer eyJ..."

python -m app.test.informes.correr_herramienta \
    --base-url https://w5vo8nfdqsfk495lkv1n78mr.187.127.35.217.sslip.io \
    --runs 2                 # 2 corridas por caso para medir estabilidad
    # --solo 7686,489        # opcional: solo algunos suministros
    # --modelo qwen3:8b      # opcional: forzar modelo LLM
```

Llama por cada caso: `GET /reclamos/reclamo/001/001/{codreclamo}/{suministro}`
(guarda token/motivo/clasificación en el server) -> `/investigacion/objetivos`
-> cada `/investigacion/<medio>` (tarjeta-lectura primero, fija la ventana) ->
`/investigacion/conclusion`. Guarda todo en `salidas/<codreclamo>_runN.json`.
El veredicto se extrae del texto del informe (no viene como campo).

### 3b. Comparar y reportar — LISTO

```bash
python -m app.test.informes.comparar          # métricas objetivas (sin LLM)
python -m app.test.informes.comparar --llm-judge   # + evaluación semántica
```

Emite `reporte.md` (+ `reporte.json`):
- **Matriz de confusión** del veredicto (agregada sobre runs).
- **Estabilidad**: si el veredicto de un caso varía entre corridas.
- **Lectura del medidor**: si la herramienta "vio" la lectura real (nº distintivo).
- **Objetivos**: nº de objetivos y determinantes; **alerta** en casos FUNDADO
  sin ningún objetivo determinante (causa típica de un INFUNDADO equivocado).
- Con `--llm-judge`: consistencia/cobertura/alucinación del resumen por medio y
  del razonamiento de la conclusión (reusa `get_llm` del proyecto).

## Estado

- [x] Extractor automático de los 10 PDFs (veredictos 100% correctos)
- [x] Confirmación humana del gold (`medio_id` + `hechos` + códigos)
- [x] Runner de la herramienta (`correr_herramienta.py`)
- [x] Comparador y reporte (`comparar.py`)
- [ ] **Ejecutar** contra la API en vivo (necesita token EMAPA vigente)

## Nota de interpretación (hallazgo del gold)

En los 3 casos **FUNDADO** el veredicto NO depende de la inspección sino de la
**caída de consumo** del medidor (fuga no visible ya reparada: p.ej. sum 7175,
oct=38 m³ vs ago/sep=469/311). Para acertar FUNDADO, la herramienta debe generar
un objetivo **determinante** sobre esa caída y asignarlo a `record_facturacion` /
`tarjeta_lectura`. Si no lo hace, dará INFUNDADO aunque los hechos estén bien: por
eso el reporte alerta "FUNDADO sin determinante".
