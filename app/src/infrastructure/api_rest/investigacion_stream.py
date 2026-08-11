"""Endpoints de streaming (NDJSON) del proceso de Investigación: las versiones
"en vivo" de los medios probatorios y de la conclusión, pensadas para que el
frontend muestre progreso mientras el usuario mira la pantalla. Sus
equivalentes sin streaming (para flujos automatizados) viven en
`investigacion.py`; ambos comparten la lógica de
application/services/investigacion/investigacion_service.py
(`stream_analisis_medio`, `medios_determinantes`).

Mismo prefix ("/investigacion") y las mismas dependencias que el router de
investigacion.py: para el frontend y para EMAPA es el mismo proceso, solo se
separó el archivo por tamaño (streaming vs. sync)."""

import time
import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.application.services.investigacion.investigacion_service import (
    stream_analisis_medio,
)
from app.src.application.services.investigacion.fundamentacion_service import (
    fundamentar_normativa_stream,
)
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoRequest,
    InformeRequest,
    ProblemaInforme,
)
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.core.model.informe_atencion import BloqueMedio

logger = logging.getLogger("api.investigacion_stream")

router = APIRouter(
    prefix="/investigacion",
    tags=["investigacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)

_DIRECTORIO_TECNICO_OPERACIONAL = Path(__file__).resolve().parents[4] / "volumes" / "operacional_data"


@router.get("/tecnico-operacional/{codreclamo}/archivo", tags=["interactivo"])
async def descargar_informe_tecnico_operacional(codreclamo: str) -> FileResponse:
    """Devuelve el PDF temporal asociado al reclamo activo."""
    documento = informe_store.obtener_documento_tecnico_operacional(codreclamo)
    ruta = Path(documento["ruta"]) if documento and documento.get("ruta") else None
    if ruta is None or not ruta.is_file():
        raise HTTPException(status_code=404, detail="No hay un informe técnico operacional cargado para este reclamo.")
    return FileResponse(
        ruta, 
        media_type="application/pdf", 
        filename=documento["nombre_archivo"], 
        content_disposition_type="inline"
    )


@router.post("/tecnico-operacional/stream", tags=["interactivo"])
async def tecnico_operacional_stream(
    file: UploadFile = File(...),
    codsuc: str = Form(...),
    codreclamo: str = Form(...),
    codcliente: str = Form(...),
    clasificacion: str = Form(...),
    meses: int = Form(12),
    modelo: str | None = Form(None),
    llm_router: LlmRouterService = Depends(get_llm_router),
) -> StreamingResponse:
    """Guarda el PDF temporal, extrae su sección II y genera el resumen LLM."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un PDF.")

    contenido = await file.read()
    if not contenido.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="El archivo no contiene un PDF válido.")
    if len(contenido) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El PDF no puede superar los 25 MB.")
    if informe_store.obtener(codreclamo) is None:
        raise HTTPException(status_code=404, detail="No hay un informe en curso para este reclamo.")

    anterior = informe_store.obtener_documento_tecnico_operacional(codreclamo)
    if anterior and anterior.get("ruta"):
        shutil.rmtree(Path(anterior["ruta"]).parent, ignore_errors=True)

    directorio = _DIRECTORIO_TECNICO_OPERACIONAL / codreclamo
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_pdf = directorio / f"{uuid.uuid4().hex}.pdf"
    ruta_pdf.write_bytes(contenido)
    informe_store.guardar_documento_tecnico_operacional(codreclamo, {
        "ruta": str(ruta_pdf),
        "nombre_archivo": file.filename,
        "texto_extraido": "",
    })

    async def generador():
        t_inicio = time.perf_counter()
        medio_id = "tecnico_operacional"
        medio_nombre = "Informe Técnico Operacional"
        try:
            analista = AnalistaMedioAgent(EmapaHttpAdapter(), llm_router, model=modelo)
            datos, problemas, _ = await run_in_threadpool(
                analista.preprocesar,
                medio_id, medio_nombre, codsuc, codcliente, meses, None, None, ruta_pdf,
            )
            datos["url_vista_previa"] = f"/investigacion/tecnico-operacional/{codreclamo}/archivo"
            informe_store.guardar_documento_tecnico_operacional(codreclamo, {
                "ruta": str(ruta_pdf),
                "nombre_archivo": file.filename,
                "texto_extraido": datos["texto_extraido"],
            })
            yield json.dumps({
                "evento": "preprocesamiento",
                "medio_id": medio_id,
                "medio_nombre": medio_nombre,
                "datos": datos,
                "problemas": [],
                "tiempo": time.perf_counter() - t_inicio,
            }, ensure_ascii=False) + "\n"

            resumen = await run_in_threadpool(
                analista.interpretar, medio_id, medio_nombre, datos, problemas, clasificacion, None,
            )
            bloque = BloqueMedio(
                medio_id=medio_id,
                medio_nombre=medio_nombre,
                entidad=datos,
                resumen=resumen,
                problemas=problemas,
            )
            informe_store.registrar_bloque(codreclamo, bloque, suministro=codcliente, clasificacion=clasificacion)
            yield json.dumps({
                "evento": "resumen",
                "medio_id": medio_id,
                "resumen": resumen,
                "tiempo": time.perf_counter() - t_inicio,
            }, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("[API tecnico-operacional] ERROR")
            yield json.dumps({"evento": "error", "medio_id": medio_id, "error": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


@router.post("/inspeccion-externa/stream", tags=["interactivo"])
async def inspeccion_externa_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_externa", "Inspección Externa", EmapaHttpAdapter(), llm_router)


@router.post("/inspeccion-interna/stream", tags=["interactivo"])
async def inspeccion_interna_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "inspeccion_interna", "Inspección Interna", EmapaHttpAdapter(), llm_router)


@router.post("/tarjeta-lectura/stream", tags=["interactivo"])
async def tarjeta_lectura_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "tarjeta_lectura", "Tarjeta de Lecturas", EmapaHttpAdapter(), llm_router)


@router.post("/corte-reapertura/stream", tags=["interactivo"])
async def corte_reapertura_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "corte_reapertura", "Cortes y Reaperturas", EmapaHttpAdapter(), llm_router)


@router.post("/record-facturacion/stream", tags=["interactivo"])
async def record_facturacion_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "record_facturacion", "Record de Facturación", EmapaHttpAdapter(), llm_router)


@router.post("/saldo-detalle/stream", tags=["interactivo"])
async def saldo_detalle_stream(request: BuscarReclamoRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return stream_analisis_medio(request, "saldo_detalle", "Saldo Detalle", EmapaHttpAdapter(), llm_router)


@router.post("/fundamentar-normativa/stream", tags=["interactivo"])
async def fundamentar_normativa_stream_endpoint(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Fundamentación normativa en streaming (NDJSON). Emite, a medida que se
    producen: ``candidatos`` (hallazgos determinantes seleccionados),
    ``articulos`` (por hallazgo) y ``fundamentacion`` (el párrafo final, que se
    guarda en el informe y se renderiza antes de la conclusión).
    Se ejecuta entre el análisis de los medios y la conclusión."""
    return fundamentar_normativa_stream(request, llm_router)


@router.post("/conclusion/stream", tags=["interactivo"])
async def generar_conclusion_stream(request: InformeRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> StreamingResponse:
    """Concluye el informe en streaming (NDJSON). Evalúa los objetivos
    determinantes contra sus hallazgos (puerta lógica) y consume el párrafo de
    fundamentación ya generado (paso /fundamentar-normativa); NO vuelve a
    fundamentar por problema. Emite:

    1. ``conclusion``: veredicto (FUNDADO/INFUNDADO) y su párrafo.
    2. ``informe``: el texto en lenguaje natural ya armado.

    Pensada para uso interactivo (el frontend muestra progreso en vivo).
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info("[API /investigacion/conclusion/stream] codreclamo=%s", request.codreclamo)

        informe = informe_store.obtener(request.codreclamo)
        if informe is None:
            yield json.dumps({
                "evento": "error",
                "error": (
                    f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                    "Busque el reclamo y analice al menos un medio antes de concluirlo."
                ),
            }, ensure_ascii=False) + "\n"
            return

        # La fundamentación normativa YA se realizó en su propio paso
        # (/investigacion/fundamentar-normativa) y quedó guardada en el informe;
        # aquí la conclusión la consume, sin volver a fundamentar por problema.
        problemas_resp: list[ProblemaInforme] = [
            ProblemaInforme(
                medio_id=bloque.medio_id,
                tipo=problema.tipo,
                detalle=problema.detalle,
                accion=problema.accion,
                responsable=problema.responsable,
                base_legal=problema.base_legal,
            )
            for bloque in informe.bloques
            for problema in bloque.problemas
        ]

        try:
            # --- Conclusión: veredicto FUNDADO/INFUNDADO ----------------------
            conclusionador = ConclusionAgent(llm_router=llm_router, model=request.modelo)
            veredicto = await run_in_threadpool(conclusionador.concluir_y_asignar, informe)
            yield json.dumps({
                "evento": "conclusion",
                "veredicto": veredicto,
                "conclusion": informe.conclusion,
            }, ensure_ascii=False) + "\n"

            # --- Cierre: texto final del informe ------------------------------
            texto = construir_texto_informe(informe)
            tiempo = time.perf_counter() - t_inicio
            yield json.dumps({
                "evento": "informe",
                "codreclamo": request.codreclamo,
                "informe": texto,
                "problemas": [p.model_dump() for p in problemas_resp],
                "tiempo": tiempo,
            }, ensure_ascii=False) + "\n"

            logger.info(
                "[API /investigacion/conclusion/stream] COMPLETADO | bloques=%d | problemas=%d | tiempo=%.2fs",
                len(informe.bloques), len(problemas_resp), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/conclusion/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")

