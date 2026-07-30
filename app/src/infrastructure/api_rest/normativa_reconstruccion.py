import logging
import re
from collections import defaultdict

from fastapi import APIRouter, Query

from app.src.application.services.rag.legal_chunker import normalizar_numero_articulo
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
from app.src.infrastructure.api_rest.schemas.normativa import (
    ArticuloReconstruido,
    Inconsistencia,
    NumeralReconstruido,
    ReconstruccionResponse,
)

logger = logging.getLogger("api.normativa.reconstruccion")

# Rearma el reglamento completo desde Qdrant (fuente de verdad tras las
# modificaciones manuales) y reporta inconsistencias, para auditar que las
# altas/bajas/ediciones de artículos quedaron consistentes.
router = APIRouter(prefix="/normativa/reglamento", tags=["normativa-reconstruccion"])


def _article_sort_key(article: str) -> tuple:
    """Ordena '60' < '62' < '62-A' < '62-B' < '63'."""
    m = re.match(r"(\d+)(?:-([A-Za-z]))?", article or "")
    if not m:
        return (10 ** 9, "")
    return (int(m.group(1)), m.group(2) or "")


def _subnumeral(article: str, numeral: str | None) -> int | None:
    """Extrae el sub-número de un numeral: '60.12' (art '60') -> 12."""
    if not numeral:
        return None
    prefijo = f"{article}."
    resto = numeral[len(prefijo):] if numeral.startswith(prefijo) else numeral
    m = re.match(r"(\d+)", resto)
    return int(m.group(1)) if m else None


def _numeral_sort_key(article: str, numeral: str | None) -> tuple:
    """El encabezado (numeral None) va primero; luego por orden numérico real."""
    if not numeral:
        return (-1,)
    nums = re.findall(r"\d+", numeral)
    return tuple(int(x) for x in nums) if nums else (0,)


@router.get("/reconstruccion", response_model=ReconstruccionResponse)
async def reconstruir_reglamento(
    coleccion: str = Query("sunass_reglamento"),
) -> ReconstruccionResponse:
    """Reconstruye el reglamento vigente (sin puntos derogados) ordenado por
    artículo y numeral, y reporta inconsistencias detectadas en la colección."""
    qdrant = QdrantAdapter()
    puntos = qdrant.get_all(collection_name=coleccion)

    activos = [p for p in puntos if (p.get("payload") or {}).get("estado") != "inactivo"]
    total_inactivos = len(puntos) - len(activos)

    # Agrupar por artículo normalizado.
    por_articulo: dict[str, list] = defaultdict(list)
    for p in activos:
        payload = p.get("payload") or {}
        art = normalizar_numero_articulo(payload.get("article", ""))
        por_articulo[art].append(p)

    articulos: list[ArticuloReconstruido] = []
    inconsistencias: list[Inconsistencia] = []
    total_numerales = 0

    for art in sorted(por_articulo, key=_article_sort_key):
        chunks = sorted(
            por_articulo[art],
            key=lambda p: _numeral_sort_key(art, (p.get("payload") or {}).get("numeral")),
        )
        total_numerales += len(chunks)

        numerales = []
        subs_vistos: dict[int, int] = defaultdict(int)
        numeral_none = 0
        modificado_por_art = None

        for p in chunks:
            payload = p.get("payload") or {}
            numeral = payload.get("numeral")
            numerales.append(
                NumeralReconstruido(
                    numeral=numeral,
                    text=payload.get("text", payload.get("texto", "")),
                    modificado_por=payload.get("modificado_por"),
                    vigencia_desde=payload.get("vigencia_desde"),
                    id=p["id"],
                )
            )
            if payload.get("modificado_por") and not modificado_por_art:
                modificado_por_art = payload.get("modificado_por")

            if numeral is None:
                numeral_none += 1
            else:
                # ¿el numeral pertenece realmente a este artículo?
                if not str(numeral).startswith(f"{art}."):
                    inconsistencias.append(
                        Inconsistencia(
                            article=art,
                            tipo="numeral_no_coincide",
                            detalle=f"El numeral '{numeral}' no corresponde al artículo {art}.",
                        )
                    )
                sub = _subnumeral(art, numeral)
                if sub is not None:
                    subs_vistos[sub] += 1

        primer_payload = (chunks[0].get("payload") or {}) if chunks else {}
        articulos.append(
            ArticuloReconstruido(
                article=art,
                titulo=primer_payload.get("titulo"),
                capitulo=primer_payload.get("capitulo"),
                subcapitulo=primer_payload.get("subcapitulo"),
                norma=primer_payload.get("norma"),
                modificado_por=modificado_por_art,
                numerales=numerales,
            )
        )

        # --- Chequeos de consistencia por artículo ---

        # 1) Encabezado suelto conviviendo con numerales (posible resto de una
        #    edición hecha con PUT en vez de /reemplazar).
        if numeral_none and len(subs_vistos) > 0:
            inconsistencias.append(
                Inconsistencia(
                    article=art,
                    tipo="chunk_suelto_con_numerales",
                    detalle=(
                        f"El artículo {art} tiene un chunk sin numeral y además "
                        f"{len(subs_vistos)} numeral(es). Revisar si el chunk suelto "
                        f"es texto viejo que debió reemplazarse."
                    ),
                )
            )

        # 2) Numerales duplicados.
        for sub, cnt in subs_vistos.items():
            if cnt > 1:
                inconsistencias.append(
                    Inconsistencia(
                        article=art,
                        tipo="numeral_duplicado",
                        detalle=f"El numeral {art}.{sub} aparece {cnt} veces activo.",
                    )
                )

        # 3) Saltos en la secuencia de numerales.
        if subs_vistos:
            lo, hi = min(subs_vistos), max(subs_vistos)
            faltantes = [i for i in range(lo, hi + 1) if i not in subs_vistos]
            if faltantes:
                inconsistencias.append(
                    Inconsistencia(
                        article=art,
                        tipo="numeral_faltante",
                        detalle=(
                            f"Faltan numerales en el artículo {art}: "
                            + ", ".join(f"{art}.{i}" for i in faltantes)
                        ),
                    )
                )

    return ReconstruccionResponse(
        status="ok",
        coleccion=coleccion,
        total_articulos=len(articulos),
        total_numerales_activos=total_numerales,
        total_inactivos=total_inactivos,
        inconsistencias=inconsistencias,
        articulos=articulos,
    )
