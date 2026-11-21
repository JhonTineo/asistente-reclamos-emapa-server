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


def calcular_point_id(article: str, numeral: str | None, parte: int = 1) -> str:
    """ID determinista (uuid5) a partir de artículo + numeral (+ parte).

    Subir el mismo artículo/numeral dos veces hace upsert (sobrescribe) en
    lugar de duplicar. Debe producir exactamente el mismo ID que usa el
    indexado del PDF base para que las modificaciones manuales lo pisen.

    `parte` > 1 identifica las continuaciones de un numeral (o de un artículo
    sin numerales) que fue partido por tamaño; la parte 1 conserva el ID
    histórico `art_numeral`.
    """
    art = normalizar_numero_articulo(article)
    unique_str = f"{art}_{numeral if numeral else 'None'}"
    if parte and parte > 1:
        unique_str += f"_p{parte}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_str))


# ---------------------------------------------------------------------------
# Troceado (chunking) de un artículo
# ---------------------------------------------------------------------------
#
# Unidad de indexado = NUMERAL ("93.2"), no el artículo completo. Un artículo
# largo regula varias situaciones; con un solo vector, este queda en el
# "promedio" de todas y no gana la búsqueda en ninguna (y si supera el contexto
# del modelo, se trunca). Reglas:
#
#   1. Si el artículo tiene numerales de 2º nivel (N.k al inicio de párrafo),
#      cada numeral es un chunk. Los de 3er nivel (N.k.j) quedan dentro de su
#      padre. Las referencias internas ("según 14.2") no cortan porque no
#      están al inicio de párrafo.
#   2. El texto previo al primer numeral (encabezado introductorio) es su
#      propio chunk; si es corto, además se antepone como CONTEXTO al texto que
#      se embebe de cada numeral.
#   3. Si un numeral (o un artículo sin numerales) supera MAX_CHARS, se parte
#      por párrafos (y, si un párrafo solo ya es enorme, por oraciones) en
#      "partes". Si el bloque abre con una frase introductoria que termina en
#      ":" ("Podrán presentar ... las siguientes personas:"), esa frase se
#      repite como contexto en las partes siguientes.

OBJETIVO_CHARS = 1000   # ~250-300 tokens: tamaño cómodo para un vector preciso
MAX_CHARS = 1600
MAX_CONTEXTO_CHARS = 350


def _partir_parrafo_largo(parrafo: str, max_chars: int) -> list[str]:
    """Parte un párrafo enorme por oraciones."""
    oraciones = re.split(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚÑ(])", parrafo)
    piezas, actual = [], ""
    for o in oraciones:
        if actual and len(actual) + len(o) + 1 > max_chars:
            piezas.append(actual.strip())
            actual = o
        else:
            actual = f"{actual} {o}" if actual else o
    if actual.strip():
        piezas.append(actual.strip())
    return piezas


def _empaquetar(parrafos: list[str], objetivo: int, max_chars: int) -> list[str]:
    """Agrupa párrafos consecutivos en bloques de ~objetivo (<= max_chars)."""
    unidades: list[str] = []
    for p in parrafos:
        unidades.extend(_partir_parrafo_largo(p, max_chars) if len(p) > max_chars else [p])

    total = sum(len(u) for u in unidades)
    if total <= max_chars:
        return ["\n".join(unidades)]

    # Reparte en n bloques de tamaño parecido (evita una última parte mínima).
    n = max(2, round(total / objetivo))
    meta = total / n
    bloques, actual, largo = [], [], 0
    for u in unidades:
        if actual and (largo + len(u) > max_chars or largo >= meta):
            bloques.append("\n".join(actual))
            actual, largo = [], 0
        actual.append(u)
        largo += len(u)
    if actual:
        bloques.append("\n".join(actual))
    return bloques


_LITERAL_RE = re.compile(r"^([a-z])\)\s")


def _agrupar_por_literal(art: str, parrafos: list[str],
                         juntar_cortos: bool = True) -> list[tuple[str | None, list[str]]] | None:
    """Agrupa los párrafos por literal a), b), c)… Solo acepta la letra que
    sigue en la secuencia: así "i)" o "v)" (numeración romana dentro de un
    literal) no abren un grupo nuevo. El numeral queda como "91 f)", que se
    cita tal cual ("Art. 91 f)"). Devuelve None si no hay al menos a) y b)."""
    grupos: list[tuple[str | None, list[str]]] = []
    siguiente = "a"
    for p in parrafos:
        m = _LITERAL_RE.match(p)
        if m and m.group(1) == siguiente:
            grupos.append((f"{art} {siguiente})", [p]))
            siguiente = chr(ord(siguiente) + 1)
        elif grupos:
            grupos[-1][1].append(p)
        else:
            grupos.append((None, [p]))
    if siguiente <= "b":
        return None
    return _juntar_literales_cortos(art, grupos) if juntar_cortos else grupos


LITERAL_CORTO = 300


def _juntar_literales_cortos(art, grupos):
    """Listas de ítems breves (Art. 73: "m) Programa de purga de redes.") darían
    chunks de 50 caracteres sin tema. Los literales CORTOS consecutivos se
    juntan hasta OBJETIVO_CHARS ("73 a)-e)"); un literal largo queda solo, así
    que el 91 f) no vuelve a pegarse al 91 e)."""
    def largo(ps):
        return sum(len(p) for p in ps)

    salida: list[list] = []   # [primera_letra, ultima_letra, parrafos]
    for numeral, ps in grupos:
        letra = numeral.split()[-1].rstrip(")") if numeral else None
        previo = salida[-1] if salida else None
        if (letra and previo and previo[0] and largo(ps) <= LITERAL_CORTO
                and previo[3] and largo(previo[2]) + largo(ps) <= OBJETIVO_CHARS):
            previo[1] = letra
            previo[2] = previo[2] + ps
        else:
            salida.append([letra, letra, list(ps), bool(letra) and largo(ps) <= LITERAL_CORTO])
    resultado = []
    for primera, ultima, ps, _ in salida:
        if not primera:
            resultado.append((None, ps))
        elif primera == ultima:
            resultado.append((f"{art} {primera})", ps))
        else:
            resultado.append((f"{art} {primera})-{ultima})", ps))
    return resultado


def agrupar_unidades(art: str, article_text: str, *, juntar_literales: bool = False,
                     max_chars: int = MAX_CHARS) -> list[tuple[str | None, list[str]]]:
    """Divide el cuerpo de un artículo en sus unidades: [(numeral, párrafos)].
    Un primer grupo con numeral None es la parte introductoria (si la hay).

    - Numerales de 2º nivel ("92.3").
    - Sin numerales, un artículo largo se divide en LITERALES ("a) …"): el
      Art. 91 de Calidad va de a) a f) y, sin esto, el literal f) (diferencia de
      lecturas válida) quedaba pegado a la cola del e) (medidores instalados por
      primera vez) y nunca salía primero.

    La usan el troceado para Qdrant (juntar_literales=True: junta los literales
    cortos para no tener chunks de 50 caracteres) y la base normativa
    (juntar_literales=False: cada literal es su propia unidad versionable)."""
    numeral_re = re.compile(rf"^({re.escape(art)}\.\d+)(?!\.\d)\.?")
    parrafos = [p.strip() for p in (article_text or "").split("\n") if p.strip()]
    if not parrafos:
        return []
    grupos: list[tuple[str | None, list[str]]] = []
    for p in parrafos:
        m = numeral_re.match(p)
        if m:
            grupos.append((m.group(1), [p]))
        elif grupos:
            grupos[-1][1].append(p)
        else:
            grupos.append((None, [p]))
    if not any(num for num, _ in grupos) and sum(len(p) for p in parrafos) > max_chars:
        por_literal = _agrupar_por_literal(art, parrafos, juntar_cortos=juntar_literales)
        if por_literal:
            grupos = por_literal
    return grupos


def trocear_articulo(
    article_number: str,
    article_text: str,
    objetivo: int = OBJETIVO_CHARS,
    max_chars: int = MAX_CHARS,
) -> list[dict]:
    """Trocea el cuerpo de un artículo (párrafos separados por "\\n").

    Devuelve dicts {article, numeral, parte, text, contexto}: `text` es lo que
    se guarda/muestra; `contexto` es texto extra que solo se antepone al
    EMBEBER (no se duplica en lo que ve el LLM).
    """
    art = normalizar_numero_articulo(article_number)
    # 1) Agrupar por numeral de 2º nivel, o por literal (ver agrupar_unidades).
    grupos = agrupar_unidades(art, article_text, juntar_literales=True, max_chars=max_chars)
    if not grupos:
        return []
    tiene_numerales = any(num for num, _ in grupos)

    # 2) Encabezado introductorio corto como contexto de los numerales.
    contexto_intro = ""
    if tiene_numerales and grupos[0][0] is None:
        intro = " ".join(grupos[0][1])
        if len(intro) <= MAX_CONTEXTO_CHARS:
            contexto_intro = intro

    # 3) Empaquetar cada grupo en partes por tamaño.
    chunks: list[dict] = []
    for numeral, ps in grupos:
        frase_intro = ps[0] if ps[0].rstrip().endswith(":") and len(ps[0]) <= MAX_CONTEXTO_CHARS else ""
        bloques = _empaquetar(ps, objetivo, max_chars)
        for i, bloque in enumerate(bloques, start=1):
            contexto = contexto_intro if numeral else ""
            if i > 1 and frase_intro:
                contexto = f"{contexto} {frase_intro}".strip()
            chunks.append({
                "article": art,
                "numeral": numeral,
                "parte": i,
                "text": bloque,
                "contexto": contexto,
            })
    return chunks


def split_numerals(article_number, article_text):
    """Compatibilidad: mismo troceado que el indexado del PDF, para que
    `POST /normativa/articulos/reemplazar` genere los mismos chunks e IDs."""
    return trocear_articulo(article_number, article_text)


def texto_para_embedding(
    *,
    norma: str | None,
    encabezado_articulo: str,
    numeral: str | None,
    parte: int,
    text: str,
    contexto: str = "",
    titulo: str | None = None,
    capitulo: str | None = None,
    subcapitulo: str | None = None,
) -> str:
    """Compone el texto que se VECTORIZA para un chunk.

    Antepone la ruta jerárquica (norma > título > capítulo > artículo >
    numeral): un numeral suelto ("93.2. En caso de...") no dice de qué trata;
    el encabezado del artículo y del capítulo le dan el tema. El texto que se
    guarda en el payload sigue siendo solo `text`.
    """
    ruta = " > ".join(x for x in (norma, titulo, capitulo, subcapitulo) if x)
    cabecera = encabezado_articulo
    if numeral:
        cabecera += f" (numeral {numeral})"
    if parte and parte > 1:
        cabecera += f" [continuación {parte}]"
    partes = [ruta, cabecera]
    if contexto:
        partes.append(contexto)
    partes.append(text)
    return "\n".join(p for p in partes if p)
