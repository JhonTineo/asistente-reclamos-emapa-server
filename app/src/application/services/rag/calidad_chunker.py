# -*- coding: utf-8 -*-
"""Chunker del TUO del Reglamento de Calidad de la Prestación de los Servicios de
Saneamiento (RCD N.º 058-2023-SUNASS-CD, El Peruano 10-10-2023, páginas 5-36).

Reemplaza a `pdf_chunk.parse_document` + `legal_chunker.split_numerals` para esta
norma. Con el índice anterior de calidad (266 puntos) esos módulos producían,
medido:

* 133 de 266 puntos con ligaturas rotas ("Veriﬁ cación"): una búsqueda por la
  palabra "notificación" da 0 aciertos;
* 37 de 134 artículos sin su encabezado ni párrafo inicial (entre ellos el 92,
  el 93 y el 107), porque se descarta todo lo anterior al primer numeral;
* 21 fragmentos de referencias cruzadas ("93.1 y", "93.2, según sea el caso.")
  como puntos aparte;
* chunks de hasta 7 539 caracteres (Art. 137 absorbe las disposiciones).

Reutiliza el mecanismo del chunker de reclamos (`reclamos_chunker`): el numeral
solo se reconoce al inicio de un bloque del PDF y solo si su primer número es el
del artículo en curso. Lo propio de este PDF: dos columnas, párrafos partidos
entre columnas/páginas, subcapítulos, notas "(Texto …)" pegadas a los
encabezados y disposiciones con ordinales ("Décima Primera").

Los anexos de la norma no están en este PDF (termina en las disposiciones
complementarias transitorias).

    python -m app.src.application.services.rag.calidad_chunker <pdf> [--json salida.json]
"""

from __future__ import annotations

import json
import re
import sys

from app.src.application.services.rag.reclamos_chunker import (
    RE_ARTICULO,
    RE_CAPITULO,
    RE_TITULO,
    ChunkNormativo,
    _Unidad,
    _inicio_cuerpo,
    extraer_bloques,
    resumen,
    validar,
)

COLECCION_CALIDAD = "sunass_reglamento"
NORMA_CALIDAD = (
    "Texto Único Ordenado del Reglamento de Calidad de la Prestación de los Servicios de "
    "Saneamiento (RCD N.º 058-2023-SUNASS-CD)"
)
NORMA_CORTA_CALIDAD = "Reglamento de Calidad"
TOTAL_ARTICULOS_CALIDAD = 137
MAX_CHARS_CALIDAD = 1500   # los artículos largos se parten por párrafos/incisos

RE_SUBCAPITULO = re.compile(r"^SUBCAP[IÍ]TULO\s+\d+", re.IGNORECASE)
RE_DISP_TRANSITORIAS_Y_FINALES = re.compile(r"^DISPOSICIONES TRANSITORIAS Y FINALES", re.IGNORECASE)
RE_DISP_COMPLEMENTARIAS = re.compile(r"^DISPOSICIONES COMPLEMENTARIAS", re.IGNORECASE)
RE_DISP_ITEM = re.compile(
    r"^(Primera|Segunda|Tercera|Cuarta|Quinta|Sexta|S[ée]ptima|Octava|Novena"
    r"|D[ée]cima(?:\s+(?:Primera|Segunda|Tercera))?)\s*\.\s*-\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_RE_NOTA_EN_ENCABEZADO = re.compile(r"\s*\((?:Texto|Disposici[oó]n)\b.*$", re.IGNORECASE | re.DOTALL)


def extraer_bloques_calidad(pdf_path: str):
    """Dos columnas; el índice de la página 1 (y < 350) se recorta; los párrafos
    partidos entre columnas o páginas se unen."""
    return extraer_bloques(
        pdf_path, dos_columnas=True, caratula=False, y_min_primera_pagina=350.0, unir_partidos=True,
    )


def _encabezado(texto: str) -> str:
    """Quita la nota "(Texto modificado por…)" que el PDF pega al encabezado."""
    return _RE_NOTA_EN_ENCABEZADO.sub("", texto).strip()


def parsear_bloques_calidad(bloques) -> list[ChunkNormativo]:
    cuerpo = bloques[_inicio_cuerpo(bloques):]

    titulo = capitulo = subcapitulo = None
    actual: _Unidad | None = None
    chunks: list[ChunkNormativo] = []
    modo = "articulos"
    kind_disp = ""
    ultimo_encabezado = None          # "titulo" | "capitulo" | "subcapitulo" | None

    def nueva_unidad(*args, **kw) -> _Unidad:
        return _Unidad(*args, **kw, subcapitulo=subcapitulo, norma=NORMA_CALIDAD,
                       norma_corta=NORMA_CORTA_CALIDAD, max_chars=MAX_CHARS_CALIDAD)

    def cerrar():
        nonlocal actual
        if actual is not None:
            chunks.extend(actual.a_chunks())
            actual = None

    for b in cuerpo:
        t = b.texto

        # --- disposiciones ------------------------------------------------
        if RE_DISP_TRANSITORIAS_Y_FINALES.match(t):
            cerrar(); modo, kind_disp, ultimo_encabezado = "disposiciones", "Transitoria y Final", None
            titulo, capitulo, subcapitulo = "DISPOSICIONES TRANSITORIAS Y FINALES", None, None
            continue
        if RE_DISP_COMPLEMENTARIAS.match(t):
            cerrar(); modo, kind_disp, ultimo_encabezado = "disposiciones", "Complementaria Transitoria", None
            titulo, capitulo, subcapitulo = "DISPOSICIONES COMPLEMENTARIAS TRANSITORIAS", None, None
            continue
        if modo == "disposiciones":
            if t.upper() == "TRANSITORIAS":          # 2.ª línea del encabezado anterior
                continue
            m = RE_DISP_ITEM.match(t)
            if m:
                cerrar()
                ordinal = re.sub(r"\s+", " ", m.group(1)).title()
                nombre = f"Disposición {kind_disp} {ordinal}"
                actual = nueva_unidad(nombre, nombre, "disposicion", nombre, titulo, None)
                actual.agregar(m.group(2).strip())
            elif actual is not None:
                actual.agregar(t)
            continue

        # --- articulado ---------------------------------------------------
        if RE_TITULO.match(t):
            cerrar(); titulo, capitulo, subcapitulo, ultimo_encabezado = _encabezado(t), None, None, "titulo"
            continue
        if RE_CAPITULO.match(t):
            cerrar(); capitulo, subcapitulo, ultimo_encabezado = _encabezado(t), None, "capitulo"
            continue
        if RE_SUBCAPITULO.match(t):
            cerrar(); subcapitulo, ultimo_encabezado = _encabezado(t), "subcapitulo"
            continue
        m = RE_ARTICULO.match(t)
        if m:
            cerrar()
            numero, nombre = m.group(1), m.group(2).strip().rstrip(".").strip()
            actual = nueva_unidad(numero, f"Artículo {numero}.- {nombre}", "articulo", nombre, titulo, capitulo)
            ultimo_encabezado = None
            continue
        # Un encabezado en MAYÚSCULAS puede venir partido en dos bloques.
        if ultimo_encabezado and actual is None and _encabezado(t).isupper() and len(t) < 90:
            texto = _encabezado(t)
            if ultimo_encabezado == "titulo":
                titulo = f"{titulo} {texto}"
            elif ultimo_encabezado == "capitulo":
                capitulo = f"{capitulo} {texto}"
            else:
                subcapitulo = f"{subcapitulo} {texto}"
            continue
        ultimo_encabezado = None
        if actual is not None:
            actual.agregar(t)
    cerrar()
    return chunks


def chunkear_calidad(pdf_path: str) -> list[ChunkNormativo]:
    return parsear_bloques_calidad(extraer_bloques_calidad(pdf_path))


def validar_calidad(chunks: list[ChunkNormativo]) -> list[str]:
    return validar(chunks, total=TOTAL_ARTICULOS_CALIDAD, max_chars=MAX_CHARS_CALIDAD)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        sys.exit("uso: python -m app.src.application.services.rag.calidad_chunker <pdf> [--json salida.json]")
    resultado = chunkear_calidad(sys.argv[1])
    print(resumen(resultado))
    for p in validar_calidad(resultado):
        print("  ! " + p)
    if "--json" in sys.argv:
        destino = sys.argv[sys.argv.index("--json") + 1]
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(
                [{"id": c.point_id(), **c.payload("pdf"), "embedding_text": c.texto_embedding()} for c in resultado],
                f, ensure_ascii=False, indent=1,
            )
        print("JSON escrito en", destino)
