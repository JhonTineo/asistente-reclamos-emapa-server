"""Carga inicial de la base normativa desde los PDFs consolidados.

Cada artículo se divide en unidades (numerales "92.3" o literales "91 f)") con
la misma lógica que el troceado de Qdrant (legal_chunker.agrupar_unidades), pero
sin juntar literales: cada literal es su propia unidad versionable.

Las notas de vigencia del PDF ("(Texto según el artículo 1 de la RCD N.º
011-2007-SUNASS-CD, modificado por ...)") no se descartan como en el índice
vectorial: son el HISTORIAL de la unidad y se guardan en su versión (nota +
lista de dispositivos).

Uso (desde la raíz del repo):
    .venv\\Scripts\\python.exe -m app.src.application.services.normativa.importar
"""

import logging
import os
import re

from app.src.application.services.rag.chunk_and_index import NORMAS, _titulo_articulo
from app.src.application.services.rag.legal_chunker import (
    ARTICLE_NUMBER_RE, agrupar_unidades, normalizar_numero_articulo,
)
from app.src.application.services.rag.pdf_chunk import (
    ANOTACION_RE, clean_article, extract_document_structure, parse_document,
)

logger = logging.getLogger("normativa.importar")

# importar.py -> normativa -> services -> application -> src
DIR_ARCHIVOS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "storage", "files",
)
_DISPOSITIVO_RE = re.compile(r"(\d{3})-(\d{4})-SUNASS-\s*CD", re.IGNORECASE)
# Notas de modificación pegadas a los encabezados de título/capítulo: van al
# historial, no a la ruta (inflaban el índice de títulos).
_NOTA_RUTA_RE = re.compile(r"\s*\((?:Texto|Cap[ií]tulo|T[ií]tulo|Subcap[ií]tulo)[^()]*\)", re.IGNORECASE)


def id_unidad(norma_id: str, articulo: str, numeral: str | None) -> str:
    """ID estable: "RC.91" (artículo), "RC.92.3" (numeral), "RC.91.f" (literal)."""
    if not numeral:
        return f"{norma_id}.{articulo}"
    literal = re.fullmatch(rf"{re.escape(articulo)}\s+([a-z])\)", numeral)
    if literal:
        return f"{norma_id}.{articulo}.{literal.group(1)}"
    return f"{norma_id}.{numeral}"


def dispositivos_de(nota: str | None) -> list[str]:
    vistos: list[str] = []
    for num, anio in _DISPOSITIVO_RE.findall(nota or ""):
        d = f"RCD {num}-{anio}-SUNASS-CD"
        if d not in vistos:
            vistos.append(d)
    return vistos


def unidades_desde_pdf(pdf_path: str, norma_id: str, is_el_peruano: bool = True) -> list[dict]:
    articulos = parse_document(extract_document_structure(pdf_path, is_el_peruano=is_el_peruano))
    unidades: list[dict] = []
    orden = 0
    for art in articulos:
        crudo = art["texto"]
        notas = [" ".join(m.split()) for m in ANOTACION_RE.findall(crudo)]
        nota = " ".join(notas) or None
        art = clean_article(art)
        m = ARTICLE_NUMBER_RE.search(art["articulo"])
        if not m:
            logger.warning("Bloque sin número de artículo, se omite: %.60s", art["articulo"])
            continue
        numero = normalizar_numero_articulo(m.group(1))
        ruta = " > ".join(
            _NOTA_RUTA_RE.sub("", x).strip()
            for x in (art["titulo"], art["capitulo"], art["subcapitulo"]) if x
        ) or None
        grupos = agrupar_unidades(numero, art["texto"])
        intro = "\n".join("\n".join(ps) for num, ps in grupos if num is None)
        tiene_hijas = any(num for num, _ in grupos)

        id_art = id_unidad(norma_id, numero, None)
        orden += 1
        unidades.append({
            "id": id_art, "tipo": "articulo", "articulo": numero, "numeral": None,
            "padre_id": None, "orden": orden, "titulo": _titulo_articulo(art["articulo"].strip()),
            "ruta": ruta, "texto": intro if tiene_hijas else art["texto"],
            "nota": nota, "dispositivos": dispositivos_de(nota),
        })
        for num, ps in grupos:
            if not num:
                continue
            orden += 1
            unidades.append({
                "id": id_unidad(norma_id, numero, num),
                "tipo": "literal" if ")" in num else "numeral",
                "articulo": numero, "numeral": num, "padre_id": id_art, "orden": orden,
                "titulo": None, "ruta": ruta, "texto": "\n".join(ps),
                # La nota del PDF es del artículo; la unidad la hereda como origen.
                "nota": None, "dispositivos": dispositivos_de(nota),
            })
    ids = [u["id"] for u in unidades]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise ValueError(f"IDs de unidad duplicados en {os.path.basename(pdf_path)}: {sorted(duplicados)}")
    return unidades


def importar_todo(repo, directorio: str = DIR_ARCHIVOS) -> dict[str, int]:
    """Carga todas las normas del catálogo (chunk_and_index.NORMAS)."""
    resultado = {}
    for orden, item in enumerate(NORMAS):
        pdf = os.path.join(directorio, item["archivo"])
        if not os.path.exists(pdf):
            logger.warning("[NORMATIVA] No se encontró %s, se omite", pdf)
            continue
        unidades = unidades_desde_pdf(pdf, item["id"], item.get("is_el_peruano", True))
        repo.importar_norma({
            "id": item["id"], "nombre": item["norma"], "resolucion": item.get("resolucion"),
            "archivo": item["archivo"], "coleccion": item["coleccion"], "orden": orden,
        }, unidades)
        resultado[item["id"]] = len(unidades)
        logger.info("[NORMATIVA] %s: %d unidades importadas", item["id"], len(unidades))
    return resultado


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    from app.src.application.services.normativa.catalogo import ruta_base_normativa
    from app.src.infrastructure.adapters.persistencia.sqlite_normativa_repository import (
        SqliteNormativaRepository,
    )
    ruta = sys.argv[1] if len(sys.argv) > 1 else ruta_base_normativa()
    print(importar_todo(SqliteNormativaRepository(ruta)), "->", ruta)
