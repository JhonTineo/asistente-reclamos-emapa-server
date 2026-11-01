"""Detección y extracción de informes operacionales narrativos y formularios."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
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
    # Datos puntuales del informe (horario, interrupciones, válvula de aire,
    # presión, conclusiones...) para el análisis y el panel de evidencias.
    # Vacío si no se pudieron leer: el texto_extraido sigue siendo la fuente.
    campos: dict = field(default_factory=dict)


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
    """Asocia las X con la opción a su izquierda en la misma fila del PDF."""
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
    return "No determinada (sin marca X legible o marcas múltiples)"


class PreTecnicoOperacionalService:
    """Detecta el formato y extrae la evidencia operacional sin consultar un LLM."""

    def preprocesar(self, ruta_pdf: Path, nombre_archivo: str) -> InformeTecnicoOperacional:
        with pymupdf.open(ruta_pdf) as documento:
            paginas = [pagina.get_text("text") for pagina in documento]
            narrativo = bool(_INICIO_SECCION_II.search("\n".join(paginas)))
            formulario = any(_es_formulario(texto) for texto in paginas)
            if narrativo and formulario:
                raise ValueError("El PDF contiene ambos formatos de informe; no se puede seleccionar uno de forma inequívoca.")
            if formulario:
                return self._extraer_formulario(documento, nombre_archivo)
            if narrativo:
                return self._extraer_narrativo(paginas, nombre_archivo)
            raise ValueError(
                "Formato de informe técnico operacional no reconocido. Se espera un informe "
                "narrativo con sección II o un formulario de reportes operacionales con texto seleccionable."
            )

    def _extraer_narrativo(self, paginas: list[str], nombre_archivo: str) -> InformeTecnicoOperacional:
        texto_completo = "\n".join(paginas)
        inicio = _INICIO_SECCION_II.search(texto_completo)
        assert inicio is not None
        fin = _SIGUIENTE_SECCION.search(texto_completo, inicio.end())
        limite = fin.start() if fin else len(texto_completo)
        texto = texto_completo[inicio.start():limite]
        texto = re.sub(r"[•●▪◦]", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        if len(texto) < 40:
            raise ValueError("La sección II del informe no contiene texto utilizable.")
        paginas_seccion = []
        offset = 0
        for numero, contenido in enumerate(paginas, 1):
            if offset < limite and offset + len(contenido) > inicio.start() and contenido.strip():
                paginas_seccion.append(numero)
            offset += len(contenido) + 1
        return InformeTecnicoOperacional(nombre_archivo, paginas_seccion, texto, "narrativo",
                                         campos_narrativo(texto_completo))

    def _extraer_formulario(self, documento: pymupdf.Document, nombre_archivo: str) -> InformeTecnicoOperacional:
        fragmentos = []
        paginas = []
        datos: dict = {}
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
            # El orden visual conserva los valores dentro de presión, observaciones y conclusiones.
            # Las filas con casillas se sustituyen por respuestas resueltas geométricamente.
            inicio = re.search(r"REPORTE\s+DE\s+INTERRUPCIONES", texto, re.I)
            fin = re.search(r"Reporte\s+de\s+presi[oó]n", texto, re.I)
            if inicio is None or fin is None or fin.start() <= inicio.start():
                raise ValueError("El formulario no contiene los límites esperados de los reportes operacionales.")
            resueltas = {etiqueta: _respuesta_casilla(pagina, etiqueta, opciones)
                         for etiqueta, opciones in campos}
            respuestas = [f"{etiqueta}: {valor}." for etiqueta, valor in resueltas.items()]
            datos = campos_formulario(texto, resueltas) if not datos else datos
            fragmentos.append("\n".join([texto[:inicio.start()], *respuestas, texto[fin.start():]]))
            paginas.append(numero)
        texto = re.sub(r"\s+", " ", "\n".join(fragmentos)).strip()
        return InformeTecnicoOperacional(nombre_archivo, paginas, texto, "formulario", datos)


# ---------------------------------------------------------------------------
# Campos puntuales del informe (no reemplazan al texto: lo resumen para el
# análisis y el panel de evidencias). Cada campo es None si no se encontró.
# No se extrae el nombre del reclamante (dato personal innecesario aquí).
# ---------------------------------------------------------------------------

def _limpio(texto: str | None) -> str | None:
    if not texto:
        return None
    t = re.sub(r"\s+", " ", texto).strip(" .:;-–")
    return t or None


def _buscar(patron: str, texto: str, flags: int = re.I | re.S) -> str | None:
    m = re.search(patron, texto, flags)
    return _limpio(m.group(1)) if m else None


def _zona(texto: str) -> str | None:
    m = re.search(r"zona\s+(alta|media|baja)", texto, re.I)
    return m.group(1).upper() if m else None


def _si_no(respuesta: str | None, si: str, no: str) -> str | None:
    """Normaliza la respuesta de una casilla a 'SI'/'NO' (None si no se leyó)."""
    if not respuesta or respuesta.startswith("No determinada"):
        return None
    r = respuesta.strip().lower()
    if r == si.lower():
        return "SI"
    if r == no.lower():
        return "NO"
    return None


def campos_formulario(texto: str, casillas: dict[str, str]) -> dict:
    """Formulario "INFORME TÉCNICO OPERACIONAL" (casillas y recuadros)."""
    presion = _buscar(r"Reporte\s+de\s+presi[oó]n\s*(.+?)\s*Observaciones", texto)
    valor_presion = None
    if presion:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*M\.?\s*C\.?\s*A", presion, re.I)
        valor_presion = float(m.group(1).replace(",", ".")) if m else None
    vpa = _si_no(casillas.get("Existencia de VPA en la zona"), "Si hay VPA", "No hay VPA")
    estado = casillas.get("Estado de la VPA")
    return {
        "numero_informe": _buscar(r"N[°º]\s*INFORME\s*:\s*([^\n]+)", texto, re.I),
        "fecha_informe": _buscar(r"FECHA\s+INFORME\s*:\s*([^\n]+)", texto, re.I),
        "ubicacion": _buscar(r"UBICACI[OÓ]N\s*:\s*([^\n]+)", texto, re.I),
        "meses_reclamados": _buscar(r"MESES\s+RECLAMADOS\s*:\s*([^\n]+)", texto, re.I),
        "horario_abastecimiento": _buscar(r"HORA\s+DE\s+SUMINISTRO\s*:\s*([^\n]+)", texto, re.I),
        "fuente_abastecimiento": _buscar(r"FUENTE\s+DE\s+ABASTECIMIENTO\s*:\s*([^\n]+)", texto, re.I),
        "zona": _zona(texto),
        "interrupciones": _si_no(casillas.get("En el periodo reclamado hubo interrupciones en el abastecimiento"), "SI", "NO"),
        "reporte_interrupciones_adjunto": _si_no(casillas.get(
            "Se adjunta reporte de interrupciones en las fuentes de abastecimiento en los meses reclamados"), "SI", "NO"),
        "existe_valvula_aire": vpa,
        "estado_valvula_aire": (estado if estado in ("Operativa", "Inoperativa") else None) if vpa != "NO" else None,
        "plano_curvas_nivel": _si_no(casillas.get("Se anexa plano de curvas de nivel"), "SI", "NO"),
        "presion": presion,
        "presion_mca": valor_presion,
        "observaciones": _buscar(r"\bObservaciones\s*(.+?)\s*Conclusiones", texto),
        "conclusiones": _buscar(r"\bConclusiones\s*(.+?)\s*(?:Nota\s*:|$)", texto),
    }


def campos_narrativo(texto: str) -> dict:
    """Informe narrativo (I Antecedentes, II Análisis, III Conclusiones)."""
    t = re.sub(r"[•●▪◦]", " ", texto)
    continuidad = _buscar(r"Continuidad\s+del\s+servicio\s*:\s*(.+?)(?:Existencia\s+de\s+v[aá]lvula|III\s*\)|$)", t)
    interrupciones = None
    if continuidad:
        if re.search(r"\bno\s+(?:se\s+)?(?:han?\s+)?(?:producido|presentado|registrado|existido)\b[^.]*interrupcion", continuidad, re.I):
            interrupciones = "NO"
        elif re.search(r"interrupcion", continuidad, re.I):
            interrupciones = "SI"
    vpa_texto = _buscar(r"Existencia\s+de\s+v[aá]lvula\s+de\s+aire\s*:\s*(.+?)(?:III\s*\)|$)", t)
    existe = estado = None
    if vpa_texto:
        if re.search(r"\bno\s+(?:existe|se\s+(?:encontr|evidenci|constat))", vpa_texto, re.I):
            existe = "NO"
        elif re.search(r"presencia\s+de|existe", vpa_texto, re.I):
            existe = "SI"
        m = re.search(r"v[aá]lvulas?\s+de\s+aire\s+(inoperativas?|operativas?)", vpa_texto, re.I)
        estado = ("Inoperativa" if m.group(1).lower().startswith("inop") else "Operativa") if m else None
    return {
        "numero_informe": _buscar(r"INFORME\s+N[°º]\s*([\w\-]+)", t),
        "fecha_informe": _buscar(r"FECHA\s*:\s*([^\n]+)", t),
        "ubicacion": _buscar(r"ubicada\s+en\s+(?:el\s+|la\s+)?(.+?),\s+en\s+el\s+distrito", t),
        "meses_reclamados": None,
        "horario_abastecimiento": _buscar(r"horario\s+de\s+abastecimiento\s+establecido[^:]*?es\s+de\s+(.+?)\.\s", t),
        "fuente_abastecimiento": _buscar(r"(Sector\s+\d+[^()\n]*)", t),
        "zona": _zona(t),
        "interrupciones": interrupciones,
        "reporte_interrupciones_adjunto": "SI" if continuidad and re.search(r"se\s+adjunta\s+evidencia", continuidad, re.I) else None,
        "existe_valvula_aire": existe,
        "estado_valvula_aire": estado if existe != "NO" else None,
        "plano_curvas_nivel": "SI" if re.search(r"plano\s+de\s+curvas\s+de\s+nivel", t, re.I) else None,
        "presion": None,
        "presion_mca": None,
        "continuidad": continuidad,
        "observaciones": None,
        "conclusiones": _buscar(r"III\s*\)\s*Conclusiones(?:\s+y\s+recomendaciones)?\s*(.+?)(?:Para\s+su\s+conocimiento|Atentamente|$)", t),
    }
