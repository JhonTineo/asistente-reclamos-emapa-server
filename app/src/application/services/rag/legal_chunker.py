import re
import uuid


# Acepta artículos con sufijo incorporado por modificatorias: "62-A", "62 - A",
# "137-B", además de los numéricos base. También la forma abreviada "Art. 126.-"
# que usa el TUO en algunos artículos. El grupo 1 es el número + sufijo crudo.
ARTICLE_NUMBER_RE = re.compile(
    r"ART(?:[IÍ]CULO|\.)\s*(\d+(?:\s*-\s*[A-Za-z])?)",
    re.IGNORECASE
)


def normalizar_numero_articulo(texto: str) -> str:
    """Normaliza cualquier forma de referirse a un artículo a su forma canónica.

    'ARTÍCULO 62-A' | '62 - a' | 'Artículo 62' -> '62-A' | '62'

    Es la clave para que el ID determinista de un artículo modificado
    manualmente coincida con el que se generó al indexar el PDF base.
    """
    if not texto:
        return ""

    match = re.search(r"(\d+)(?:\s*-\s*([A-Za-z]))?", str(texto))

    if not match:
        return str(texto).strip()

    base = match.group(1)
    sufijo = match.group(2)

    return f"{base}-{sufijo.upper()}" if sufijo else base


def calcular_point_id(article: str, numeral: str | None) -> str:
    """ID determinista (uuid5) a partir de artículo + numeral.

    Subir el mismo artículo/numeral dos veces hace upsert (sobrescribe) en
    lugar de duplicar. Debe producir exactamente el mismo ID que usa el
    indexado del PDF base para que las modificaciones manuales lo pisen.
    """
    art = normalizar_numero_articulo(article)
    unique_str = f"{art}_{numeral if numeral else 'None'}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))


def split_numerals(article_number, article_text):

    art_re = re.escape(str(article_number))

    numeral_pattern = re.compile(
        rf"({art_re}\.\d+.*?)"
        rf"(?={art_re}\.\d+|$)",
        re.DOTALL
    )

    numerals = []

    matches = list(
        numeral_pattern.finditer(article_text)
    )

    if len(matches) == 0:

        return [
            {
                "article": article_number,
                "numeral": None,
                "text": article_text
            }
        ]

    for match in matches:

        chunk = match.group(1).strip()

        numeral_match = re.match(
            rf"({art_re}\.\d+)",
            chunk
        )

        numeral = (
            numeral_match.group(1)
            if numeral_match
            else None
        )

        numerals.append(
            {
                "article": article_number,
                "numeral": numeral,
                "text": chunk
            }
        )

    return numerals
