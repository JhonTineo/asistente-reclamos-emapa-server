"""Extracción de la sección II de informes técnicos operacionales."""

from __future__ import annotations

import re
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


class PreTecnicoOperacionalService:
    """Obtiene exclusivamente la sección II del informe técnico operacional."""

    def preprocesar(self, ruta_pdf: Path, nombre_archivo: str) -> InformeTecnicoOperacional:
        with pymupdf.open(ruta_pdf) as documento:
            paginas = [pagina.get_text("text") for pagina in documento]

        texto_completo = "\n".join(paginas)
        inicio = _INICIO_SECCION_II.search(texto_completo)
        if not inicio:
            raise ValueError("No se encontró la sección II) Análisis Ubicación y horario de abastecimiento.")

        fin = _SIGUIENTE_SECCION.search(texto_completo, inicio.end())
        texto = texto_completo[inicio.start(): fin.start() if fin else len(texto_completo)]
        texto = re.sub(r"[•]", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        if len(texto) < 40:
            raise ValueError("La sección II del informe no contiene texto utilizable.")

        paginas_seccion = [i + 1 for i, contenido in enumerate(paginas) if _INICIO_SECCION_II.search(contenido)]
        return InformeTecnicoOperacional(
            nombre_archivo=nombre_archivo,
            paginas=paginas_seccion or [1],
            texto_extraido=texto,
        )
