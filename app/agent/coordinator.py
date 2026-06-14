import json
import time
import logging
import asyncio
from pathlib import Path
from app.agent.analista_medio import AnalistaMedioAgent
from app.tools.emapa_client import consultar_medio_probatorio

logger = logging.getLogger("agent.coordinator")

MEDIOS_PATH = Path(__file__).parent.parent / "storage" / "medios_probatorios_v1.json"


def _cargar_medios() -> list[dict]:
    return json.loads(MEDIOS_PATH.read_text(encoding="utf-8"))["medios_probatorios"]


def _obtener_params_para_medio(medio_id: str, codsuc: str, codcliente: str, codreclamo: str, anio: str) -> dict:
    params = {"codsuc": codsuc}

    if medio_id in ("saldo_actual", "tarjeta_lectura", "corte_reapertura"):
        params["codcliente"] = codcliente
    elif medio_id == "record_facturacion":
        params["codcliente"] = codcliente
        params["anio"] = anio
    elif medio_id in ("inspeccion_externa", "inspeccion_interna"):
        params["codcliente"] = codcliente

    return params


async def _analisis_medio_sync(
    medio_id: str,
    medio_nombre: str,
    datos: str,
    clasificacion: str,
    modelo: str | None,
) -> dict:
    """Ejecuta el análisis de un medio en thread separado para no bloquear."""
    return await asyncio.to_thread(
        _ejecutar_analisis_medio,
        medio_id,
        medio_nombre,
        datos,
        clasificacion,
        modelo,
    )


def _ejecutar_analisis_medio(
    medio_id: str,
    medio_nombre: str,
    datos: str,
    clasificacion: str,
    modelo: str | None,
) -> dict:
    """Ejecuta el análisis real del medio (bloqueante)."""
    analista = AnalistaMedioAgent(model=modelo)
    return analista.analizar(
        medio_id=medio_id,
        medio_nombre=medio_nombre,
        datos=datos,
        clasificacion=clasificacion,
    )


async def analizar_medios(
    codsuc: str,
    codcliente: str,
    codreclamo: str,
    clasificacion: str,
    anio: str,
    modelo: str | None = None,
) -> list[dict]:
    """
    Obtiene y analiza todos los medios probatorios en paralelo.
    """
    t_inicio_total = time.perf_counter()
    medios = _cargar_medios()

    logger.info("=" * 60)
    logger.info("[FASE 1] INICIO - Análisis de %d medios probatorios", len(medios))
    logger.info("[FASE 1] codsuc=%s | codcliente=%s | codreclamo=%s", codsuc, codcliente, codreclamo)
    logger.info("[FASE 1] clasificacion=%s | anio=%s", clasificacion, anio)
    logger.info("=" * 60)

    async def procesar_un_medio(medio: dict, numero: int, total: int) -> dict:
        medio_id = medio["id"]
        medio_nombre = medio["nombre"]
        t_medio_inicio = time.perf_counter()

        params = _obtener_params_para_medio(medio_id, codsuc, codcliente, codreclamo, anio)

        logger.info("-" * 40)
        logger.info("[MEDIO %d/%d] Iniciando: %s", numero, total, medio_nombre)
        logger.info("[MEDIO %d/%d] Params: %s", numero, total, params)

        logger.info("[MEDIO %d/%d] Consultando API EMAPA...", numero, total)
        t_api_inicio = time.perf_counter()

        result = consultar_medio_probatorio.execute(medio_id=medio_id, params=params)

        t_api = time.perf_counter() - t_api_inicio

        if not result.success:
            logger.error("[MEDIO %d/%d] ERROR en API: %s (%.2fs)", numero, total, result.error, t_api)
            return {
                "medio_id": medio_id,
                "medio_nombre": medio_nombre,
                "resumen": f"Error al obtener datos: {result.error}",
                "estado": "error",
                "error": result.error,
            }

        logger.info("[MEDIO %d/%d] API OK | datos_recibidos=%d bytes (%.2fs)",
                   numero, total, len(result.data or ""), t_api)

        logger.info("[MEDIO %d/%d] Analizando con LLM (en thread separado)...", numero, total)
        t_analisis_inicio = time.perf_counter()

        analisis = await _analisis_medio_sync(
            medio_id, medio_nombre, result.data or "", clasificacion, modelo
        )

        t_analisis = time.perf_counter() - t_analisis_inicio
        t_medio = time.perf_counter() - t_medio_inicio

        logger.info("[MEDIO %d/%d] COMPLETADO | tiempo_total=%.2fs (api=%.2fs, analisis=%.2fs)",
                   numero, total, t_medio, t_api, t_analisis)
        logger.info("[MEDIO %d/%d] Resumen: %s",
                   numero, total, (analisis["resumen"][:100] + "...") if len(analisis["resumen"]) > 100 else analisis["resumen"])

        return {
            "medio_id": medio_id,
            "medio_nombre": medio_nombre,
            "resumen": analisis["resumen"],
            "estado": "ok",
        }

    logger.info("[FASE 1] Lanzando analisis en paralelo de %d medios...", len(medios))
    t_paralelo_inicio = time.perf_counter()

    tareas = [
        procesar_un_medio(medio, i + 1, len(medios))
        for i, medio in enumerate(medios)
    ]
    resultados = await asyncio.gather(*tareas)

    t_paralelo = time.perf_counter() - t_paralelo_inicio
    t_total = time.perf_counter() - t_inicio_total

    logger.info("=" * 60)
    logger.info("[FASE 1] COMPLETADA")
    logger.info("[FASE 1] Resultados:")
    for r in resultados:
        estado_icon = "OK" if r["estado"] == "ok" else "ERROR"
        logger.info("[FASE 1]   [%s] %s", estado_icon, r["medio_nombre"])
    logger.info("[FASE 1] Tiempo total: %.2fs (analisis paralelo: %.2fs)", t_total, t_paralelo)
    logger.info("=" * 60)

    return list(resultados)
