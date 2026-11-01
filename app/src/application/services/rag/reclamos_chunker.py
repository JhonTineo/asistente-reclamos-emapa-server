# -*- coding: utf-8 -*-
"""Chunker del TUO del Reglamento General de Reclamos de Usuarios de Servicios de
Saneamiento (Resolución de Consejo Directivo N.º 015-2023-SUNASS-CD).

No reutiliza ``pdf_chunk.parse_document`` + ``legal_chunker.split_numerals``
porque, sobre este PDF, producen:

* el índice (páginas 3-4) como "artículos" falsos y los artículos de la propia
  resolución ("Artículo 1º.- Aprobar...") mezclados con los del reglamento;
* el Art. 46 con ~51 000 caracteres (absorbe disposiciones, anexos y formatos);
* texto de los anexos con las columnas de las tablas entrelazadas;
* ligaturas rotas ("Veriﬁ cación", "notiﬁ cación") dentro del texto indexado;
* numerales detectados en cualquier parte del texto (una referencia cruzada
  como "artículo 4.b)" o "93.1 y 93.2" abre un chunk falso).

Aquí el numeral solo se reconoce al INICIO de un bloque del PDF y solo si su
primer número coincide con el del artículo en curso.

Solo depende de pymupdf (sin Ollama ni Qdrant), así que se puede probar offline:

    python -m app.src.application.services.rag.reclamos_chunker <pdf> [--json salida.json]
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass, field

import pymupdf

COLECCION_RECLAMOS = "sunass_reclamos"
NORMA = (
    "Texto Único Ordenado del Reglamento General de Reclamos de Usuarios de "
    "Servicios de Saneamiento (RCD N.º 015-2023-SUNASS-CD)"
)
NORMA_CORTA = "Reglamento de Reclamos"
TOTAL_ARTICULOS = 46      # según el Artículo 1º de la resolución aprobatoria
MAX_CHARS = 2200          # por encima de esto un numeral se parte por párrafos


# --------------------------------------------------------------------------- #
# Limpieza de texto
# --------------------------------------------------------------------------- #
_LIGATURAS = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
_RE_LIGATURA_Y_ESPACIO = re.compile("([ﬀ-ﬄ]) ")


def normalizar_texto(texto: str) -> str:
    """Colapsa espacios y repara las ligaturas del PDF de El Peruano, que llegan
    como "Veriﬁ cación" (ligatura + espacio espurio). No usa NFKC a propósito:
    convertiría "Nº" en "No"."""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto)
    texto = _RE_LIGATURA_Y_ESPACIO.sub(r"\1", texto)
    for ligatura, equivalente in _LIGATURAS.items():
        texto = texto.replace(ligatura, equivalente)
    return texto.strip()


@dataclass
class Bloque:
    pagina: int
    x0: float
    y0: float
    texto: str
    columna: int = 0


_RE_RUIDO = re.compile(r"NORMAS\s+LEGALES|^El\s+Peruano\b|Firmado por:", re.IGNORECASE)
_Y_MAX_ENCABEZADO = 72    # los encabezados de página caen en y≈61-64


_RE_FIN_DE_FRASE = re.compile(r"[.:;)”\"]$")
_RE_INICIO_DE_ITEM = re.compile(r"^(?:[a-z]|[ivx]{1,4})\)\s")


def unir_continuaciones(bloques: list[Bloque]) -> list[Bloque]:
    """Une un párrafo que el PDF partió entre columnas o páginas: el bloque
    siguiente empieza en minúscula (y no es un inciso "a)") y el anterior no
    cerró la frase."""
    unidos: list[Bloque] = []
    for b in bloques:
        if (
            unidos
            and (b.texto[0].islower() or RE_REFERENCIA_CRUZADA.match(b.texto))
            and not _RE_INICIO_DE_ITEM.match(b.texto)
            and not _RE_FIN_DE_FRASE.search(unidos[-1].texto)
        ):
            unidos[-1] = Bloque(unidos[-1].pagina, unidos[-1].x0, unidos[-1].y0, unidos[-1].texto + " " + b.texto)
        else:
            unidos.append(b)
    return unidos


def extraer_bloques(
    pdf_path: str,
    dos_columnas: bool = False,
    caratula: bool = True,
    y_min_primera_pagina: float = 0.0,
    unir_partidos: bool = False,
) -> list[Bloque]:
    """PDF -> bloques de texto (uno por párrafo) en orden de lectura, sin los
    encabezados de página.

    Por defecto es el formato del TUO de Reclamos (carátula en la página 1 y
    una sola columna). Para el de Calidad: `caratula=False`,
    `y_min_primera_pagina=350` (recorta el índice de la página 1),
    `dos_columnas=True` y `unir_partidos=True`."""
    doc = pymupdf.open(pdf_path)
    bloques: list[Bloque] = []
    try:
        for pagina in doc:
            if pagina.number == 0 and caratula:
                continue
            for b in pagina.get_text("dict")["blocks"]:
                if b["type"] != 0:
                    continue
                texto = normalizar_texto(
                    " ".join(s["text"] for linea in b["lines"] for s in linea["spans"])
                )
                if not texto:
                    continue
                x0, y0 = b["bbox"][0], b["bbox"][1]
                if _RE_RUIDO.search(texto) and y0 < _Y_MAX_ENCABEZADO:
                    continue
                if pagina.number == 0 and y0 < y_min_primera_pagina:
                    continue
                columna = 1 if dos_columnas and x0 >= pagina.rect.width / 2 else 0
                bloques.append(Bloque(pagina.number + 1, x0, y0, texto, columna))
    finally:
        doc.close()
    # Una columna: orden de lectura = (página, y). Dos columnas: columna izquierda
    # de arriba abajo y luego la derecha.
    bloques.sort(key=lambda b: (b.pagina, b.columna, b.y0, b.x0))
    return unir_continuaciones(bloques) if unir_partidos else bloques


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #
@dataclass
class ChunkNormativo:
    article: str                 # "14" | "Disposición Transitoria Primera" | "ANEXO 3"
    numeral: str | None          # "14.2" | "B.1.1" | None
    tipo_unidad: str             # numeral | preambulo | articulo | disposicion | anexo
    titulo_articulo: str
    text: str
    titulo: str | None = None
    capitulo: str | None = None
    origen: list[str] = field(default_factory=list)
    parte: int = 1
    partes: int = 1
    subcapitulo: str | None = None
    norma: str = NORMA
    norma_corta: str = NORMA_CORTA

    def point_id(self) -> str:
        # Misma fórmula que normativa_articulos._calcular_point_id, para que los
        # endpoints de mantenimiento (buscar/eliminar por artículo) encuentren
        # estos puntos. Es única dentro de la colección (ver `validar`).
        clave = f"{self.article}_{self.numeral}"
        if self.partes > 1:
            clave += f"#p{self.parte}"
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, clave))

    def texto_embedding(self) -> str:
        """Texto que se vectoriza: SOLO el cuerpo (sin la línea "Artículo N.- Título").

        Está aparte de `text` (lo que se muestra y se le da al LLM). Medido con
        nomic-embed-text sobre el gold (app/test/rag), vectorizar el cuerpo solo
        rinde MÁS que anteponer título/capítulo/artículo: MRR 0,775 vs 0,690 sin
        prefijos de tarea y 0,875 vs 0,682 con ellos. El encabezado se repite en
        todos los numerales del artículo y los vuelve casi indistinguibles."""
        cabecera, _, cuerpo = self.text.partition("\n")
        return cuerpo or cabecera

    def payload(self, source: str) -> dict:
        return {
            "norma": self.norma,
            "norma_corta": self.norma_corta,
            "source": source,
            "titulo": self.titulo,
            "capitulo": self.capitulo,
            "subcapitulo": self.subcapitulo,
            "article": self.article,
            "numeral": self.numeral,
            "titulo_articulo": self.titulo_articulo,
            "tipo_unidad": self.tipo_unidad,
            "origen": self.origen,
            "parte": self.parte,
            "partes": self.partes,
            "text": self.text,
        }


# --------------------------------------------------------------------------- #
# Patrones
# --------------------------------------------------------------------------- #
_ORDINALES = r"PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[EÉ]PTIMO"
RE_TITULO = re.compile(rf"^T[IÍ]TULO\s+({_ORDINALES})\b", re.IGNORECASE)
RE_CAPITULO = re.compile(r"^CAP[IÍ]TULO\s+\d+", re.IGNORECASE)
# El cuerpo escribe "Artículo 14.- Inspección"; el índice, "Artículo 14. Inspección"
# (sin guion) y la resolución, "Artículo 1º.-". Solo el primero es un artículo.
# Calidad escribe "Art. 126.-" en tres artículos (126, 127 y 129).
RE_ARTICULO = re.compile(r"^Art(?:[ií]culo|\.)\s*(\d+)\s*\.\s*-\s*(.+)$", re.IGNORECASE | re.DOTALL)
# Numeral real: "93.3. Predio…" o "14.2  El día…" (con punto, o sin punto pero con
# mayúscula). "93.3 del presente reglamento" es una referencia cruzada, no un numeral.
RE_NUMERAL = re.compile(r"^(\d{1,3})\.(\d{1,3})(?:\.\s+|\s+(?=[A-ZÁÉÍÓÚ¿“\"]))\S")   # hasta 137.x en Calidad
RE_REFERENCIA_CRUZADA = re.compile(r"^\d{1,3}\.\d{1,3}(?:,|\s+(?=[a-záéíóú]))")
RE_ORIGEN = re.compile(r"^\(\s*(Texto|Disposici[oó]n)\b.*\)\s*$", re.IGNORECASE | re.DOTALL)
RE_DISP_TRANSITORIAS = re.compile(r"^DISPOSICIONES TRANSITORIAS", re.IGNORECASE)
RE_DISP_FINAL = re.compile(r"^DISPOSICI[OÓ]N FINAL", re.IGNORECASE)
RE_DISP_ITEM = re.compile(
    r"^(Primera|Segunda|Tercera|Cuarta|Quinta|[ÚU]nica)\s*\.\s*-\s*(.+)$", re.IGNORECASE | re.DOTALL
)
RE_ANEXO = re.compile(r"^ANEXO\s*(?:N\s*[°º]\s*)?(\d)\b", re.IGNORECASE)
RE_ANEXO3_FIN_SECCION_1 = re.compile(r"^2\.\s*RECLAMOS COMERCIALES NO RELATIVOS", re.IGNORECASE)


def _es_encabezado(texto: str) -> bool:
    return bool(RE_TITULO.match(texto) or RE_CAPITULO.match(texto))


def _sin_parentesis(nota: str) -> str:
    return re.sub(r"\s+", " ", nota.strip().strip("()").strip())


# --------------------------------------------------------------------------- #
# Articulado (Art. 1-46) y disposiciones
# --------------------------------------------------------------------------- #
class _Unidad:
    """Un artículo o una disposición en construcción: lista de secciones
    (numeral, bloques) y las notas de origen ("Texto modificado por...")."""

    def __init__(self, article, encabezado, tipo, titulo_articulo, titulo, capitulo,
                 subcapitulo=None, norma=NORMA, norma_corta=NORMA_CORTA, max_chars=MAX_CHARS):
        self.article = article
        self.encabezado = encabezado              # "Artículo 14.- Inspección"
        self.tipo = tipo                          # "articulo" | "disposicion"
        self.titulo_articulo = titulo_articulo
        self.titulo = titulo
        self.capitulo = capitulo
        self.subcapitulo = subcapitulo
        self.norma = norma
        self.norma_corta = norma_corta
        self.max_chars = max_chars
        self.secciones: list[list] = [[None, []]]
        self.origen: list[str] = []

    @property
    def numero(self) -> str | None:
        return self.article if self.tipo == "articulo" else None

    def agregar(self, texto: str) -> None:
        if RE_ORIGEN.match(texto):
            self.origen.append(_sin_parentesis(texto))
            return
        if self.numero is not None:
            m = RE_NUMERAL.match(texto)
            if m and m.group(1) == self.numero:
                self.secciones.append([f"{m.group(1)}.{m.group(2)}", [texto]])
                return
        self.secciones[-1][1].append(texto)

    def a_chunks(self) -> list[ChunkNormativo]:
        con_numerales = any(num for num, _ in self.secciones)
        chunks: list[ChunkNormativo] = []
        for numeral, bloques in self.secciones:
            if not bloques:
                continue
            if numeral:
                tipo_unidad = "numeral"
            elif self.tipo == "disposicion":
                tipo_unidad = "disposicion"
            else:
                tipo_unidad = "preambulo" if con_numerales else "articulo"
            chunks.extend(
                _partir(
                    base=ChunkNormativo(
                        article=self.article, numeral=numeral, tipo_unidad=tipo_unidad,
                        titulo_articulo=self.titulo_articulo, text="",
                        titulo=self.titulo, capitulo=self.capitulo, origen=list(self.origen),
                        subcapitulo=self.subcapitulo, norma=self.norma, norma_corta=self.norma_corta,
                    ),
                    encabezado=self.encabezado,
                    bloques=bloques,
                    max_chars=self.max_chars,
                )
            )
        return chunks


def _partir(base: ChunkNormativo, encabezado: str, bloques: list[str],
            max_chars: int = MAX_CHARS) -> list[ChunkNormativo]:
    """Arma el/los chunk(s) de una sección: `encabezado` + párrafos. Si excede
    `max_chars` se reparte por párrafos (el numeral se conserva y cambia `parte`)."""
    grupos: list[list[str]] = [[]]
    largo = len(encabezado)
    for b in bloques:
        if grupos[-1] and largo + len(b) > max_chars:
            grupos.append([])
            largo = len(encabezado)
        grupos[-1].append(b)
        largo += len(b) + 1
    resultado = []
    for i, grupo in enumerate(grupos, start=1):
        resultado.append(
            ChunkNormativo(
                article=base.article, numeral=base.numeral, tipo_unidad=base.tipo_unidad,
                titulo_articulo=base.titulo_articulo, titulo=base.titulo, capitulo=base.capitulo,
                origen=list(base.origen), parte=i, partes=len(grupos),
                subcapitulo=base.subcapitulo, norma=base.norma, norma_corta=base.norma_corta,
                text=encabezado + "\n" + "\n".join(grupo),
            )
        )
    return resultado


def _inicio_cuerpo(bloques: list[Bloque]) -> int:
    """Índice del primer bloque del cuerpo: el primer 'Artículo N.- ...' (el
    índice no lleva guion), retrocediendo hasta incluir su TÍTULO/CAPÍTULO."""
    i0 = next((i for i, b in enumerate(bloques) if RE_ARTICULO.match(b.texto)), None)
    if i0 is None:
        raise ValueError("No se encontró ningún 'Artículo N.-' en el PDF: ¿es el TUO de Reclamos?")
    j = i0
    while j > 0 and _es_encabezado(bloques[j - 1].texto):
        j -= 1
    return j


# --------------------------------------------------------------------------- #
# Anexos 2 y 3 (tablas)
# --------------------------------------------------------------------------- #
def _lineas(bloques: list[Bloque]) -> list[tuple[str, bool]]:
    """[(texto, es_origen)] en orden de lectura."""
    return [(b.texto, bool(RE_ORIGEN.match(b.texto))) for b in bloques]


def _chunks_anexo2(bloques: list[Bloque]) -> list[ChunkNormativo]:
    """Anexo 2 (plazos): dos chunks, comerciales y operacionales. Cada fila trae
    el plazo al final ("... 2 días"), así que el texto en orden de lectura es
    legible."""
    encabezado = (
        "Anexo N.º 2.- Plazos para la solicitud de atención de problemas operacionales y "
        "comerciales no relativos a la facturación (plazo máximo para solucionar el problema, "
        "contado desde la presentación de la solicitud)"
    )
    origen, grupos, actual = [], {"comerciales": [], "operacionales": []}, "comerciales"
    for texto, es_origen in _lineas(bloques):
        if es_origen:
            origen.append(_sin_parentesis(texto))
        elif texto.upper().startswith("PROBLEMAS OPERACIONALES"):
            actual = "operacionales"
        elif texto.upper().startswith("PROBLEMAS COMERCIALES"):
            actual = "comerciales"
        elif actual and texto[0] not in "*" and not re.match(r"^(Plazo M[aá]ximo|\(d[ií]as)", texto, re.I) \
                and not texto.upper().startswith(("PLAZOS PARA", "Y COMERCIALES", "ANEXO")):
            grupos[actual].append(texto)
    rotulos = {"comerciales": "Problemas comerciales no relativos a la facturación",
               "operacionales": "Problemas operacionales"}
    return [
        ChunkNormativo(
            article="ANEXO 2", numeral=clave, tipo_unidad="anexo",
            titulo_articulo="Plazos para la solicitud de atención de problemas",
            text=f"{encabezado}\n{rotulos[clave]}:\n" + "\n".join(lineas),
            titulo="ANEXOS", capitulo="ANEXO N.º 2", origen=origen,
        )
        for clave, lineas in grupos.items() if lineas
    ]


_RE_SUBTIPO = re.compile(r"^(\d)\.\s+(\S.{2,90})$")


def _chunks_anexo3_facturacion(bloques: list[Bloque]) -> list[ChunkNormativo]:
    """Anexo 3, sección 1 (reclamos comerciales relativos a la facturación): un
    chunk por tipo de reclamo (consumo medido, consumo promedio, ...) con los
    medios de prueba mínimos y su responsable. Las secciones 2 y 3 son tablas de
    varias columnas cuyo orden de lectura no se reconstruye con fiabilidad desde
    el PDF y quedan fuera (ver `pendientes` en el informe)."""
    encabezado_base = "Anexo N.º 3.- Medios de prueba por reclamo. 1. Reclamos comerciales relativos a la facturación"
    origen: list[str] = []
    secciones: list[tuple[str, str, list[str]]] = []   # (clave, rotulo, lineas)
    clave, rotulo, lineas = "A", "A. Información y documentación general", []
    grupo = "A"

    def cerrar():
        if lineas:
            secciones.append((clave, rotulo, list(lineas)))

    for texto, es_origen in _lineas(bloques):
        if es_origen:
            origen.append(_sin_parentesis(texto))
            continue
        up = texto.upper()
        if up.startswith(("ANEXO", "MEDIOS DE PRUEBA POR RECLAMO", "LOS MEDIOS DE PRUEBA CONTENIDOS",
                          "1. RECLAMOS COMERCIALES RELATIVOS", "MEDIO PROBATORIO")):
            continue
        if up.startswith("A. INFORMACI"):
            cerrar(); clave, rotulo, lineas, grupo = "A", "A. Información y documentación general", [], "A"
            continue
        if up.startswith("B. INFORMACI"):
            continue
        m_grupo = re.match(r"^(B\.[123])\.?\s+(Reclamos referidos .+)$", texto)
        if m_grupo:
            cerrar(); grupo = m_grupo.group(1)
            clave, rotulo, lineas = grupo, f"{grupo}. {m_grupo.group(2).rstrip(':')}", []
            if grupo == "B.2":   # el único tipo de B.2 es "Tipo de tarifa"
                pass
            continue
        if up.startswith("TIPO DE TARIFA"):
            cerrar(); clave, rotulo, lineas = "B.2", "B.2. Reclamos referidos a la tarifa aplicada: Tipo de tarifa", []
            continue
        m = _RE_SUBTIPO.match(texto)
        if m and len(texto) < 95 and grupo in ("B.1", "B.3"):
            cerrar()
            clave, rotulo, lineas = f"{grupo}.{m.group(1)}", f"{grupo}.{m.group(1)}. {m.group(2).rstrip(':')}", []
            continue
        lineas.append(texto)
    cerrar()

    return [
        ChunkNormativo(
            article="ANEXO 3", numeral=clave, tipo_unidad="anexo",
            titulo_articulo="Medios de prueba por reclamo",
            text=f"{encabezado_base}\n{rotulo}\nMedios de prueba mínimos (medio probatorio y responsable):\n"
                 + "\n".join(lineas),
            titulo="ANEXOS", capitulo="ANEXO N.º 3", origen=origen,
        )
        for clave, rotulo, lineas in secciones
    ]


# --------------------------------------------------------------------------- #
# Parser principal
# --------------------------------------------------------------------------- #
def parsear_bloques(bloques: list[Bloque]) -> list[ChunkNormativo]:
    cuerpo = bloques[_inicio_cuerpo(bloques):]

    titulo: str | None = None
    capitulo: str | None = None
    actual: _Unidad | None = None
    chunks: list[ChunkNormativo] = []
    modo = "articulos"
    kind_disp = ""
    ultimo_encabezado = None          # "titulo" | "capitulo" | None
    anexo2: list[Bloque] = []
    anexo3: list[Bloque] = []

    def cerrar():
        nonlocal actual
        if actual is not None:
            chunks.extend(actual.a_chunks())
            actual = None

    for b in cuerpo:
        t = b.texto

        # --- anexos -------------------------------------------------------
        m_anexo = RE_ANEXO.match(t) if modo != "fin" else None
        if m_anexo:
            cerrar()
            modo = f"anexo{m_anexo.group(1)}"
            continue
        if modo in ("anexo1", "anexo4"):
            continue
        if modo == "anexo2":
            anexo2.append(b)
            continue
        if modo == "anexo3":
            if RE_ANEXO3_FIN_SECCION_1.match(t):
                modo = "fin"
            else:
                anexo3.append(b)
            continue
        if modo == "fin":
            continue

        # --- disposiciones ------------------------------------------------
        if RE_DISP_TRANSITORIAS.match(t):
            cerrar(); modo, kind_disp, ultimo_encabezado = "disposiciones", "Transitoria", None
            titulo, capitulo = "DISPOSICIONES TRANSITORIAS", None
            continue
        if RE_DISP_FINAL.match(t):
            cerrar(); modo, kind_disp, ultimo_encabezado = "disposiciones", "Final", None
            titulo, capitulo = "DISPOSICIÓN FINAL", None
            continue
        if modo == "disposiciones":
            m = RE_DISP_ITEM.match(t)
            if m:
                cerrar()
                ordinal = m.group(1).capitalize().replace("Unica", "Única")
                nombre = f"Disposición {kind_disp} {ordinal}"
                actual = _Unidad(nombre, nombre, "disposicion", nombre, titulo, None)
                actual.agregar(m.group(2).strip())
            elif actual is not None:
                actual.agregar(t)
            continue

        # --- articulado ---------------------------------------------------
        if RE_TITULO.match(t):
            cerrar(); titulo, capitulo, ultimo_encabezado = t, None, "titulo"
            continue
        if RE_CAPITULO.match(t):
            cerrar(); capitulo, ultimo_encabezado = t, "capitulo"
            continue
        m = RE_ARTICULO.match(t)
        if m:
            cerrar()
            numero, nombre = m.group(1), m.group(2).strip().rstrip(".").strip()
            actual = _Unidad(numero, f"Artículo {numero}.- {nombre}", "articulo", nombre, titulo, capitulo)
            ultimo_encabezado = None
            continue
        # Un encabezado en MAYÚSCULAS puede venir partido en dos bloques:
        # "TÍTULO SEGUNDO: ... COMERCIALES NO" + "RELATIVOS A LA FACTURACIÓN".
        if ultimo_encabezado and actual is None and t.isupper() and len(t) < 90:
            if ultimo_encabezado == "titulo":
                titulo = f"{titulo} {t}"
            else:
                capitulo = f"{capitulo} {t}"
            continue
        ultimo_encabezado = None
        if actual is not None:
            actual.agregar(t)
    cerrar()

    chunks.extend(_chunks_anexo2(anexo2))
    chunks.extend(_chunks_anexo3_facturacion(anexo3))
    return chunks


def chunkear_reclamos(pdf_path: str) -> list[ChunkNormativo]:
    return parsear_bloques(extraer_bloques(pdf_path))


# --------------------------------------------------------------------------- #
# Validación (sin red)
# --------------------------------------------------------------------------- #
def validar(chunks: list[ChunkNormativo], total: int = TOTAL_ARTICULOS, max_chars: int = MAX_CHARS) -> list[str]:
    """Devuelve la lista de problemas encontrados (vacía = chunks sanos).
    `total` = cantidad de artículos que debe tener la norma."""
    problemas: list[str] = []
    ids: dict[str, ChunkNormativo] = {}
    for c in chunks:
        pid = c.point_id()
        if pid in ids:
            problemas.append(f"ID duplicado: {c.article}/{c.numeral} (pisaría a un punto existente)")
        ids[pid] = c
        if len(c.text) < 40:
            problemas.append(f"Chunk casi vacío: {c.article}/{c.numeral} ({len(c.text)} chars)")
        if len(c.text) > max_chars * 1.3:
            problemas.append(f"Chunk demasiado largo: {c.article}/{c.numeral} ({len(c.text)} chars)")
        if re.search("[ﬀ-ﬄ]", c.text):
            problemas.append(f"Ligatura sin reparar en {c.article}/{c.numeral}")
        # "diario oficial El Peruano" en el texto es legítimo; el encabezado de página no.
        if re.search(r"NORMAS LEGALES|El Peruano\s*/", c.text):
            problemas.append(f"Encabezado de página dentro de {c.article}/{c.numeral}")
        if len(re.findall(r"Art[ií]culo\s+\d+\.\s+[A-ZÁÉÍÓÚ]", c.text)) >= 3:
            problemas.append(f"Parece un índice, no un artículo: {c.article}/{c.numeral}")
        if c.numeral and c.tipo_unidad == "numeral" and c.article.isdigit():
            if c.numeral.split(".")[0] != c.article:
                problemas.append(f"Numeral {c.numeral} dentro del artículo {c.article}")
    articulos = {c.article for c in chunks if c.article.isdigit()}
    esperados = {str(n) for n in range(1, total + 1)}
    if esperados - articulos:
        problemas.append(f"Artículos que faltan: {sorted(esperados - articulos, key=int)}")
    if articulos - esperados:
        problemas.append(f"Artículos que sobran: {sorted(articulos - esperados, key=int)}")
    return problemas


def resumen(chunks: list[ChunkNormativo]) -> str:
    por_tipo: dict[str, int] = {}
    for c in chunks:
        por_tipo[c.tipo_unidad] = por_tipo.get(c.tipo_unidad, 0) + 1
    largos = sorted(len(c.text) for c in chunks)
    return (
        f"{len(chunks)} chunks {por_tipo} | largo min/mediana/max = "
        f"{largos[0]}/{largos[len(largos) // 2]}/{largos[-1]} caracteres"
    )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) < 2:
        sys.exit("uso: python -m app.src.application.services.rag.reclamos_chunker <pdf> [--json salida.json]")
    resultado = chunkear_reclamos(sys.argv[1])
    print(resumen(resultado))
    for p in validar(resultado):
        print("  ! " + p)
    if "--json" in sys.argv:
        destino = sys.argv[sys.argv.index("--json") + 1]
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(
                [{"id": c.point_id(), **c.payload("pdf"), "embedding_text": c.texto_embedding()} for c in resultado],
                f, ensure_ascii=False, indent=1,
            )
        print("JSON escrito en", destino)
