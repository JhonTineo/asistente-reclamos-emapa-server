"""Servicio de aplicación para la FUNDAMENTACIÓN NORMATIVA.

Flujo (nuevo diseño): a partir del informe ya analizado (con sus objetivos y los
medios probatorios resumidos), produce UN párrafo de fundamentación normativa:

  1. Reúne los problemas de los medios DETERMINANTES (los de los objetivos
     determinantes) y, agrupados por objetivo + con el motivo, el LLM selecciona
     los 1-3 problemas determinantes (marca `seleccionado` en ellos).
  2. Recupera los artículos SUNASS SOLO de los problemas seleccionados.
  3. Redacta un único párrafo de fundamentación y lo guarda en
     `informe.fundamentacion_normativa` (se renderiza antes de la conclusión).

Al front se le envía la lista COMPLETA de problemas de los medios determinantes
(con el flag `seleccionado`) para pintarlos como tarjetas, resaltando los
seleccionados; los artículos van solo en los seleccionados.

Lo usan el endpoint streaming (progreso en vivo) y el sync (automatización),
ambos en investigacion_stream.py / investigacion.py.
"""

import time
import json
import logging

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.investigacion import InformeRequest

logger = logging.getLogger("services.fundamentacion_service")


def _crear_agente(llm_router: LlmRouterService, modelo: str | None) -> FundamentacionNormativaAgent:
    return FundamentacionNormativaAgent(qdrant=QdrantAdapter(), llm_router=llm_router, model=modelo)


def _candidatos_payload(informe) -> list[dict]:
    """Lista COMPLETA de problemas de los medios determinantes (tarjetas del
    front), con el flag `seleccionado` ya resuelto por la selección."""
    medios_det = FundamentacionNormativaAgent._medios_determinantes(informe)
    out: list[dict] = []
    for bloque in informe.bloques:
        if bloque.medio_id not in medios_det:
            continue
        for p in bloque.problemas:
            out.append({
                "medio_id": bloque.medio_id,
                "medio_nombre": bloque.medio_nombre,
                "tipo": p.tipo,
                "detalle": p.detalle,
                "seleccionado": p.seleccionado,
                "articulos": p.articulos or [],
            })
    return out


def _medio_por_problema(informe) -> dict[int, str]:
    """id(problema) -> medio_id, para etiquetar los eventos de artículos."""
    m: dict[int, str] = {}
    for bloque in informe.bloques:
        for p in bloque.problemas:
            m[id(p)] = bloque.medio_id
    return m


def fundamentar_normativa_stream(
    request: InformeRequest, llm_router: LlmRouterService,
) -> StreamingResponse:
    """Fundamentación normativa en streaming (NDJSON). Emite:
      - ``candidatos``: lista completa de problemas de medios determinantes,
        con flag `seleccionado` (tarjetas del front).
      - ``articulos``: artículos recuperados por cada problema seleccionado.
      - ``fundamentacion``: el párrafo final (y se guarda en el informe).
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info("[API /investigacion/fundamentar-normativa/stream] codreclamo=%s", request.codreclamo)

        informe = informe_store.obtener(request.codreclamo)
        if informe is None:
            yield json.dumps({
                "evento": "error",
                "error": (
                    f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                    "Busque el reclamo y analice los medios antes de fundamentar."
                ),
            }, ensure_ascii=False) + "\n"
            return
        if not informe.objetivos:
            yield json.dumps({
                "evento": "error",
                "error": "El informe no tiene objetivos. Ejecute /investigacion/objetivos primero.",
            }, ensure_ascii=False) + "\n"
            return

        clasificacion = request.clasificacion or informe.clasificacion or ""
        motivo = informe.motivo or ""
        fundamentador = _crear_agente(llm_router, request.modelo)

        try:
            # --- Paso 1: selección de problemas determinantes (marca flags) ---
            _limpiar_seleccion(informe)
            seleccionados = await run_in_threadpool(fundamentador.seleccionar_determinantes, informe)

            # Lista completa de tarjetas (con seleccionado ya resuelto).
            yield json.dumps({
                "evento": "candidatos",
                "problemas": _candidatos_payload(informe),
            }, ensure_ascii=False) + "\n"

            if not seleccionados:
                # Sin problemas determinantes: nada que fundamentar. Se limpia el
                # párrafo y la conclusión resolverá (todo correcto → INFUNDADO).
                informe.fundamentacion_normativa = None
                tiempo = time.perf_counter() - t_inicio
                yield json.dumps({
                    "evento": "fundamentacion",
                    "codreclamo": request.codreclamo,
                    "fundamentacion": None,
                    "tiempo": tiempo,
                }, ensure_ascii=False) + "\n"
                logger.info(
                    "[API /investigacion/fundamentar-normativa/stream] Sin problemas determinantes | tiempo=%.2fs",
                    tiempo,
                )
                logger.info("=" * 60)
                return

            # --- Paso 2: RAG SOLO de los seleccionados ------------------------
            medio_por_prob = _medio_por_problema(informe)
            articulos_por_problema: list[list[dict]] = []
            for p in seleccionados:
                articulos = await run_in_threadpool(fundamentador.fundamentar_articulos, p, motivo)
                articulos_por_problema.append(articulos)
                yield json.dumps({
                    "evento": "articulos",
                    "medio_id": medio_por_prob.get(id(p)),
                    "detalle": p.detalle,
                    "articulos": p.articulos,
                }, ensure_ascii=False) + "\n"

            # --- Paso 3: redacción del párrafo --------------------------------
            parrafo = await run_in_threadpool(
                fundamentador.redactar_parrafo,
                seleccionados, articulos_por_problema, motivo, clasificacion,
            )
            informe.fundamentacion_normativa = parrafo or None

            tiempo = time.perf_counter() - t_inicio
            yield json.dumps({
                "evento": "fundamentacion",
                "codreclamo": request.codreclamo,
                "fundamentacion": parrafo,
                "tiempo": tiempo,
            }, ensure_ascii=False) + "\n"

            logger.info(
                "[API /investigacion/fundamentar-normativa/stream] COMPLETADO | seleccionados=%d | tiempo=%.2fs",
                len(seleccionados), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/fundamentar-normativa/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


def _limpiar_seleccion(informe) -> None:
    """Resetea `seleccionado`/`articulos` de los problemas de medios determinantes
    antes de re-seleccionar (permite re-fundamentar sin arrastrar una corrida
    anterior)."""
    medios_det = FundamentacionNormativaAgent._medios_determinantes(informe)
    for bloque in informe.bloques:
        if bloque.medio_id in medios_det:
            for p in bloque.problemas:
                p.seleccionado = False
                p.articulos = []


async def fundamentar_normativa_sync(
    request: InformeRequest, llm_router: LlmRouterService,
) -> dict:
    """Versión sin streaming (automatización). Genera y guarda el párrafo y
    devuelve un dict con el resultado para que el endpoint arme el response."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /investigacion/fundamentar-normativa] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if not informe:
        raise HTTPException(status_code=404, detail=f"No hay informe en curso para {request.codreclamo}")
    if not informe.objetivos:
        raise HTTPException(
            status_code=400,
            detail="El informe no tiene objetivos. Ejecute /investigacion/objetivos primero.",
        )

    clasificacion = request.clasificacion or informe.clasificacion or ""
    motivo = informe.motivo or ""
    fundamentador = _crear_agente(llm_router, request.modelo)

    _limpiar_seleccion(informe)
    seleccionados = await run_in_threadpool(fundamentador.seleccionar_determinantes, informe)
    if not seleccionados:
        informe.fundamentacion_normativa = None
        tiempo = time.perf_counter() - t_inicio
        logger.info("[API /investigacion/fundamentar-normativa] Sin problemas determinantes | tiempo=%.2fs", tiempo)
        logger.info("=" * 60)
        return {"codreclamo": request.codreclamo, "fundamentacion": None, "tiempo": tiempo}

    articulos_por_problema: list[list[dict]] = []
    for p in seleccionados:
        articulos = await run_in_threadpool(fundamentador.fundamentar_articulos, p, motivo)
        articulos_por_problema.append(articulos)
    parrafo = await run_in_threadpool(
        fundamentador.redactar_parrafo, seleccionados, articulos_por_problema, motivo, clasificacion,
    )
    informe.fundamentacion_normativa = parrafo or None

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/fundamentar-normativa] COMPLETADO | seleccionados=%d | tiempo=%.2fs",
        len(seleccionados), tiempo,
    )
    logger.info("=" * 60)
    return {
        "codreclamo": request.codreclamo,
        "fundamentacion": parrafo,
        "tiempo": tiempo,
    }
