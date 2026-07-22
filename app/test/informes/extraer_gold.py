"""Extrae un JSON dorado (borrador) de cada informe de atención real (PDF).

Los informes reales de EMAPA tienen una estructura muy regular:

    INFORME Nº 0307-2023-...
    REF: RECLAMO Nº 223463 SUMINISTRO Nº 7686
    "...siguiente resultado:"
    1. <inspección externa: medidor, lectura, predio>
    2. <inspección interna: aparatos sanitarios, fugas>
    3. <facturación / categoría>
    4. (opcional) <análisis normativo: cita Art. 88.3 SUNASS>
    "En consecuencia, ... se declara fundado/infundado."

Este script segmenta esa estructura de forma automática y deja un JSON
BORRADOR por informe. El mapeo punto->medio y los "hechos" quedan como
sugerencia (heurística) para que un humano los CONFIRME antes de comparar
(ver README del harness).

Uso:
    python -m app.test.informes.extraer_gold \
        --pdf-dir "D:/JhonTineo/Desktop/test_informe" \
        --out-dir app/test/informes/gold
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF


# --- Bloque normativo boilerplate (Art. 88.3 SUNASS) ---------------------
# Se repite casi literal entre informes; se detecta para NO mezclarlo con la
# descripción de un medio y para marcar el punto como "análisis normativo".
_MARCADORES_NORMA = (
    "sunass",
    "88.3",
    "88°",
    "resolución de concejo directivo",
    "resolucion de consejo directivo",
    "reglamento de calidad",
    "diferencia de lecturas",
)


def _norm(s: str) -> str:
    """Colapsa espacios/saltos de línea manteniendo el texto legible y quita la
    cabecera/pie de página ('EMAPA SAN MARTIN S.A.') que se cuela entre hojas."""
    s = s.replace("\xa0", " ")
    s = re.sub(r"EMAPA\s+SAN\s+MARTIN\s+S\.?A\.?", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", " ", s)
    return s.strip()


def _sin_acentos_lower(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def extraer_texto(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    return "".join(pg.get_text() for pg in doc)


def _buscar(patron: str, texto: str, grupo: int = 1) -> str | None:
    m = re.search(patron, texto, re.IGNORECASE)
    return m.group(grupo).strip() if m else None


def parsear_header(texto: str) -> dict:
    numero = _buscar(r"INFORME\s+N\S*\s*(\d{3,4}-\d{4})", texto)
    # [^\d]* absorbe el "Nº"/espacios/guiones entre la etiqueta y el número,
    # tanto si el informe escribió "RECLAMO Nº 223365" como "RECLAMO 223573-".
    codreclamo = _buscar(r"RECLAMO[^\d]{0,6}(\d{5,})", texto)
    suministro = _buscar(r"SUMINISTRO[^\d]{0,6}(\d+)", texto)
    fecha = _buscar(r"FECHA\s*:?\s*([^\n]+)", texto)
    return {
        "numero": numero,
        "codreclamo": codreclamo,
        "suministro": suministro,
        "fecha": _norm(fecha) if fecha else None,
    }


def _clasificar_punto(texto_punto: str) -> str:
    """Sugerencia heurística de a qué medio corresponde un punto numerado.
    El humano CONFIRMA/corrige esto en el gold definitivo."""
    t = _sin_acentos_lower(texto_punto)
    # El análisis normativo tiene prioridad: el punto que cita la norma suele
    # repetir "medidor"/"inspección", así que se detecta ANTES que los medios.
    if any(m in t for m in _MARCADORES_NORMA):
        return "analisis_normativo"  # NO es un medio: alimenta conclusión/fundamentación
    if "inspeccion interna" in t or ("interna" in t and "inodoro" in t):
        return "inspeccion_interna"
    if "inspeccion" in t and ("medidor" in t or "lectura" in t):
        return "inspeccion_externa"
    if "facturacion" in t and ("categoria" in t or "domestico" in t or "comercial" in t):
        return "record_facturacion"
    return "desconocido"


def segmentar_puntos(cuerpo: str) -> list[dict]:
    """Divide el cuerpo (entre 'siguiente resultado:' y 'En consecuencia')
    en puntos numerados y sugiere el medio de cada uno."""
    # Divide en '\n 1. ', '\n 2. ', ...
    partes = re.split(r"\n\s*(\d+)\.\s", "\n" + cuerpo)
    # partes = ['', '1', 'texto1', '2', 'texto2', ...]
    puntos = []
    for i in range(1, len(partes) - 1, 2):
        num = partes[i]
        texto = _norm(partes[i + 1])
        puntos.append({
            "n": int(num),
            "texto_real": texto,
            "medio_sugerido": _clasificar_punto(texto),
            # Campos a CONFIRMAR por el humano:
            "medio_id": None,          # <- confirmar mapeo al medio de la herramienta
            "hechos": {},              # <- llenar datos estructurados (lectura, inodoros, ...)
        })
    return puntos


def extraer_conclusion(texto: str) -> dict:
    m = re.search(
        r"(En consecuencia.*?)(?:Sin otro particular|Atentamente|C\.c\.)",
        texto, re.IGNORECASE | re.DOTALL,
    )
    conclusion = _norm(m.group(1)) if m else None
    veredicto = None
    if conclusion:
        mv = re.search(r"se\s+declara\s+\**\s*(fundado|infundado)", conclusion, re.IGNORECASE)
        if mv:
            veredicto = mv.group(1).upper()
    return {"conclusion_real": conclusion, "veredicto_real": veredicto}


def parsear_informe(pdf_path: Path) -> dict:
    texto = extraer_texto(pdf_path)
    header = parsear_header(texto)

    m_cuerpo = re.search(
        r"siguiente resultado\s*:?(.*?)(?:En consecuencia)",
        texto, re.IGNORECASE | re.DOTALL,
    )
    cuerpo = m_cuerpo.group(1) if m_cuerpo else ""
    puntos = segmentar_puntos(cuerpo)
    conclusion = extraer_conclusion(texto)

    return {
        "_archivo": pdf_path.name,
        "_revisado_por_humano": False,   # poner True cuando se confirme el mapeo/hechos
        **header,
        # Datos que EMAPA necesita y NO están en el PDF (llenar a mano):
        "codsede": None,
        "codsuc": None,
        "codcliente": None,   # normalmente = suministro; confirmar
        "puntos": puntos,
        **conclusion,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    print(f"Encontrados {len(pdfs)} PDF(s)")
    for pdf in pdfs:
        data = parsear_informe(pdf)
        stem = re.sub(r"[^0-9A-Za-z_-]+", "_", pdf.stem)[:60]
        out = out_dir / f"{stem}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        v = data.get("veredicto_real")
        n_pts = len(data["puntos"])
        medios = [p["medio_sugerido"] for p in data["puntos"]]
        print(f"  OK {pdf.name[:45]:45} | rec={data.get('codreclamo')} sum={data.get('suministro')} "
              f"| veredicto={v} | puntos={n_pts} {medios}")


if __name__ == "__main__":
    main()
