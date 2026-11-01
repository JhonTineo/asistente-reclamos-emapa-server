"""Detección y extracción de informes operacionales narrativos y formularios."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf


_INICIO_SECCION_II = re.compile(
    r"II\s*\)\s*An[aá]lisis\s+Ubicaci[oó]n\s+y\s+horario\s+de\s+abastecimiento\s*:",
    re.IGNORECASE,
)
_SIGUIENTE_SECCION = re.compile(r"\bIII\s*\)", re.IGNORECASE)


@dataclass
class InformeTecnicoOperacional:
    nombre_archivo: str
    paginas: list[int]
    texto_extraido: str
    formato: str = "narrativo"


def _normalizar(texto: str) -> str:
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c))
        .upper().split()
    )


def _es_formulario(texto: str) -> bool:
    normalizado = _normalizar(texto)
    return all(marca in normalizado for marca in (
        "INFORME TECNICO OPERACIONAL", "DATOS DEL PREDIO",
        "REPORTE DE INTERRUPCIONES", "REPORTE DE VALVULAS DE PURGA DE AIRE",
    ))


def _respuesta_casilla(pagina: pymupdf.Page, etiqueta: str, opciones: tuple[str, str]) -> str:
    """Asocia las X con la opci?n a su izquierda en la misma fila del PDF."""
    filas = pagina.search_for(etiqueta)
    if len(filas) != 1:
        return "No determinada (fila ausente o ambigua)"
    fila = filas[0]
    centro_y = (fila.y0 + fila.y1) / 2
    candidatos = []
    for opcion in opciones:
        cajas = [r for r in pagina.search_for(opcion)
                 if r.x0 >= fila.x1 and abs((r.y0 + r.y1) / 2 - centro_y) <= 10]
        cajas = [r for r in cajas if not any(
            otra.lower() != opcion.lower() and opcion.lower() in otra.lower()
            and any(caja.contains(r) for caja in pagina.search_for(otra))
            for otra in opciones
        )]
        if len(cajas) != 1:
            return "No determinada (opciones ambiguas)"
        candidatos.append(cajas[0])
    seleccionadas = []
    for x0, y0, x1, y1, palabra, *_ in pagina.get_text("words"):
        if palabra.upper() != "X" or abs((y0 + y1) / 2 - centro_y) > 10:
            continue
        cercanas = [(x0 - caja.x1, opcion) for caja, opcion in zip(candidatos, opciones)
                    if 0 <= x0 - caja.x1 <= 35]
        if cercanas:
            seleccionadas.append(min(cercanas)[1])
    if len(seleccionadas) == 1:
        return seleccionadas[0]
    return "No determinada (sin marca X legible o marcas m?ltiples)"


class PreTecnicoOperacionalService:
    """Detecta el formato y extrae la evidencia operacional sin consultar un LLM."""

    def preprocesar(self, ruta_pdf: Path, nombre_archivo: str) -> InformeTecnicoOperacional:
        with pymupdf.open(ruta_pdf) as documento:
            paginas = [pagina.get_text("text") for pagina in documento]
            narrativo = bool(_INICIO_SECCION_II.search("\n".join(paginas)))
            formulario = any(_es_formulario(texto) for texto in paginas)
            if narrativo and formulario:
                raise ValueError("El PDF contiene ambos formatos de informe; no se puede seleccionar uno de forma inequ?voca.")
            if formulario:
                return self._extraer_formulario(documento, nombre_archivo)
            if narrativo:
                return self._extraer_narrativo(paginas, nombre_archivo)
            raise ValueError(
                "Formato de informe t?cnico operacional no reconocido. Se espera un informe "
                "narrativo con secci?n II o un formulario de reportes operacionales con texto seleccionable."
            )

    def _extraer_narrativo(self, paginas: list[str], nombre_archivo: str) -> InformeTecnicoOperacional:
        texto_completo = "\n".join(paginas)
        inicio = _INICIO_SECCION_II.search(texto_completo)
        assert inicio is not None
        fin = _SIGUIENTE_SECCION.search(texto_completo, inicio.end())
        limite = fin.start() if fin else len(texto_completo)
        texto = texto_completo[inicio.start():limite]
        texto = re.sub(r"[??]", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        if len(texto) < 40:
            raise ValueError("La secci?n II del informe no contiene texto utilizable.")
        paginas_seccion = []
        offset = 0
        for numero, contenido in enumerate(paginas, 1):
            if offset < limite and offset + len(contenido) > inicio.start() and contenido.strip():
                paginas_seccion.append(numero)
            offset += len(contenido) + 1
        return InformeTecnicoOperacional(nombre_archivo, paginas_seccion, texto, "narrativo")

    def _extraer_formulario(self, documento: pymupdf.Document, nombre_archivo: str) -> InformeTecnicoOperacional:
        fragmentos = []
        paginas = []
        campos = (
            ("En el periodo reclamado hubo interrupciones en el abastecimiento", ("SI", "NO")),
            ("Se adjunta reporte de interrupciones en las fuentes de abastecimiento en los meses reclamados", ("SI", "NO")),
            ("Existencia de VPA en la zona", ("Si hay VPA", "No hay VPA")),
            ("Estado de la VPA", ("Operativa", "Inoperativa")),
            ("Se anexa plano de curvas de nivel", ("SI", "NO")),
        )
        for numero, pagina in enumerate(documento, 1):
            if not _es_formulario(pagina.get_text()):
                continue
            texto = pagina.get_text(sort=True)
            # El orden visual conserva los valores dentro de presi?n, observaciones y conclusiones.
            # Las filas con casillas se sustituyen por respuestas resueltas geom?tricamente.
            inicio = re.search(r"REPORTE\s+DE\s+INTERRUPCIONES", texto, re.I)
            fin = re.search(r"Reporte\s+de\s+presi[o?]n", texto, re.I)
            if inicio is None or fin is None or fin.start() <= inicio.start():
                raise ValueError("El formulario no contiene los l?mites esperados de los reportes operacionales.")
            respuestas = [f"{etiqueta}: {_respuesta_casilla(pagina, etiqueta, opciones)}."
                          for etiqueta, opciones in campos]
            fragmentos.append("\n".join([texto[:inicio.start()], *respuestas, texto[fin.start():]]))
            paginas.append(numero)
        texto = re.sub(r"\s+", " ", "\n".join(fragmentos)).strip()
        return InformeTecnicoOperacional(nombre_archivo, paginas, texto, "formulario")
