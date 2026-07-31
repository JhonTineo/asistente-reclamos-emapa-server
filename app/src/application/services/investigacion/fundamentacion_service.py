"""Servicio de aplicación para la FUNDAMENTACIÓN NORMATIVA.

Dos modos, sobre el mismo endpoint:

  - AUTOMÁTICO (request.seleccion is None): el LLM selecciona los 1-3 problemas
    determinantes de los medios determinantes; por cada uno se recuperan sus
    artículos (RAG) y otro paso (`marcar_aplica`) marca cuáles regulan el
    problema; se redacta el párrafo con los artículos que aplican.

  - MANUAL (request.seleccion presente): NO se usa el selector por LLM. Se usan
    exactamente los problemas que el usuario marcó como determinantes en el
    front. Para cada uno: si trae artículos curados, se usan tal cual; si no
    (problema recién marcado), se recuperan por RAG + `marcar_aplica`. El párrafo
    usa solo los artículos con `aplica=true`.

Al front se le envía la lista COMPLETA de problemas de los medios determinantes
(con `seleccionado`) para las tarjetas; los artículos van solo en los
seleccionados. El párrafo se guarda en `informe.fundamentacion_normativa`.
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


def _aplicar_seleccion_manual(informe, seleccion) -> list[tuple]:
    """Aplica la selección manual del front (por `medio_id`+`detalle`): marca
    `seleccionado` y fija los artículos curados provistos. Devuelve una lista de
    tuplas (problema, needs_rag), donde needs_rag=True si el item no trajo
    artículos (problema recién marcado, hay que recuperarlos)."""
    _limpiar_seleccion(informe)
    idx: dict[tuple[str, str], object] = {}
    for bloque in informe.bloques:
        for p in bloque.problemas:
            idx[(bloque.medio_id, p.detalle)] = p

    pares: list[tuple] = []
    for item in seleccion:
        problema = idx.get((item.medio_id, item.detalle))
        if problema is None:
            logger.warning(
                "[FUNDAMENTACION] selección manual sin match: medio=%s detalle=%s",
                item.medio_id, item.detalle,
            )
            continue
        problema.seleccionado = True
        if item.articulos is None:
            pares.append((problema, True))
        else:
            problema.articulos = [a.model_dump() for a in item.articulos]
            pares.append((problema, False))
    return pares


def _rag_y_marcar(fundamentador: FundamentacionNormativaAgent, problema, clasificacion: str, motivo: str) -> list[dict]:
    """RAG de los artículos + relevancia (`marcar_aplica`) en un solo paso
    bloqueante (para un único run_in_threadpool)."""
    raw = fundamentador.buscar_articulos(problema, motivo)
    return fundamentador.marcar_aplica(problema, raw, clasificacion, motivo)


async def _resolver_seleccion(informe, request, fundamentador) -> list[tuple]:
    """Devuelve [(problema, needs_rag)] según el modo:
    - manual (request.seleccion presente): usa la selección del usuario.
    - automático: el LLM elige y todos requieren RAG."""
    if request.seleccion is not None:
        return _aplicar_seleccion_manual(informe, request.seleccion)
    _limpiar_seleccion(informe)
    seleccionados = await run_in_threadpool(fundamentador.seleccionar_determinantes, informe)
    return [(p, True) for p in seleccionados]


def fundamentar_normativa_stream(
    request: InformeRequest, llm_router: LlmRouterService,
) -> StreamingResponse:
    """Fundamentación normativa en streaming (NDJSON). Emite `candidatos`
    (tarjetas con flag), `articulos` (por seleccionado, con `aplica`) y
    `fundamentacion` (el párrafo final, que se guarda en el informe)."""

    async def generador():
        t_inicio = time.perf_counter()
        modo = "manual" if request.seleccion is not None else "auto"
        logger.info("=" * 60)
        logger.info(
            "[API /investigacion/fundamentar-normativa/stream] codreclamo=%s | modo=%s",
            request.codreclamo, modo,
        )

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
            # --- Paso 1: selección (auto por LLM o manual del front) ----------
            pares = await _resolver_seleccion(informe, request, fundamentador)
            seleccionados = [p for p, _ in pares]

            # Lista completa de tarjetas (con seleccionado ya resuelto).
            yield json.dumps({
                "evento": "candidatos",
                "problemas": _candidatos_payload(informe),
            }, ensure_ascii=False) + "\n"

            if not seleccionados:
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

            # --- Paso 2: artículos por seleccionado ---------------------------
            # needs_rag=True → RAG + relevancia; False → ya vienen curados del front.
            medio_por_prob = _medio_por_problema(informe)
            for problema, needs_rag in pares:
                if needs_rag:
                    problema.articulos = await run_in_threadpool(
                        _rag_y_marcar, fundamentador, problema, clasificacion, motivo,
                    )
                yield json.dumps({
                    "evento": "articulos",
                    "medio_id": medio_por_prob.get(id(problema)),
                    "detalle": problema.detalle,
                    "articulos": problema.articulos,
                }, ensure_ascii=False) + "\n"

            # --- Paso 3: redacción del párrafo (solo artículos que aplican) ---
            parrafo = await run_in_threadpool(
                fundamentador.redactar_parrafo, seleccionados, motivo, clasificacion,
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
                "[API /investigacion/fundamentar-normativa/stream] COMPLETADO | modo=%s | seleccionados=%d | tiempo=%.2fs",
                modo, len(seleccionados), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/fundamentar-normativa/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


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

    pares = await _resolver_seleccion(informe, request, fundamentador)
    seleccionados = [p for p, _ in pares]
    if not seleccionados:
        informe.fundamentacion_normativa = None
        tiempo = time.perf_counter() - t_inicio
        logger.info("[API /investigacion/fundamentar-normativa] Sin problemas determinantes | tiempo=%.2fs", tiempo)
        logger.info("=" * 60)
        return {"codreclamo": request.codreclamo, "fundamentacion": None, "tiempo": tiempo}

    for problema, needs_rag in pares:
        if needs_rag:
            problema.articulos = await run_in_threadpool(
                _rag_y_marcar, fundamentador, problema, clasificacion, motivo,
            )
    parrafo = await run_in_threadpool(
        fundamentador.redactar_parrafo, seleccionados, motivo, clasificacion,
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
