import re

from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore


def generar_slug(texto: str) -> str:
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", "", texto)
    texto = re.sub(r"\s+", "_", texto)
    return texto


def generar_embeddings(chunks: list[str]) -> list[list[float]]:
    if not chunks:
        return []
    embedder = EmbeddingService()
    vectores = []
    for chunk in chunks:
        vector = embedder.encode(chunk)
        vectores.append(vector)
    return vectores


def indexar_en_qdrant(
    chunks: list[str],
    vectores: list[list[float]],
    metadata: list[dict],
    coleccion: str
) -> int:
    if not chunks or not vectores or not metadata:
        return 0
    embedder = EmbeddingService()
    qdrant = QdrantStore()
    qdrant.create_collection(coleccion, embedder.dimension)
    points = []
    import uuid
    for i, (chunk, vector, meta) in enumerate(zip(chunks, vectores, metadata)):
        punto = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk)),
            "vector": vector,
            "payload": {
                "tipo": meta.get("tipo", ""),
                "descripcion": meta.get("descripcion", ""),
                "conceptos": meta.get("conceptos", []),
                "palabras_clave": meta.get("palabras_clave", []),
                "categoria": meta.get("categoria", ""),
                "subcategoria": meta.get("subcategoria", ""),
                "grupo": meta.get("grupo", ""),
                "slug": generar_slug(meta.get("tipo", ""))
            }
        }
        points.append(punto)
    qdrant.upsert(points, collection_name=coleccion)

    return len(points)


def clean(text):
    return re.sub(r"\s+", " ", text.replace("**", "")).strip()


def extract_concepts(text):
    keywords = [
        "consumo", "consumir", "medidor", "lectura", "facturación", "facturar",
        "recibo", "cobro", "cobrar", "m3", "servicio", "pago", "pagado",
        "suministro", "alcantarillado", "tarifa", "reclamo", "promedio",
        "asignación", "usuario anterior", "cruce", "procesado", "concepto",
        "cargo", "unidad", "instalación", "conexión", "factibilidad",
        "trámite", "filtración", "fuga", "mantenimiento", "deterioro",
        "daño", "caja de medidor", "reubicación", "atoro", "taponamiento",
        "desagüe", "predio", "agua externa", "conexión domiciliaria",
        "instalar", "cerrado", "inactivo", "duplicado", "exceso",
        "estudio de factibilidad", "informe de factibilidad"
    ]
    text_lower = text.lower()
    return [k for k in keywords if k.lower() in text_lower]


def build_chunk(reclamo):
    conceptos = ", ".join(reclamo.get("conceptos", []))
    palabras_clave = ", ".join(reclamo.get("palabras_clave", []))
    return f"""Tipo de reclamo: {reclamo.get('tipo', '')}
            Categoría: {reclamo.get('categoria', '')}
            Subcategoría: {reclamo.get('subcategoria', '')}
            Grupo: {reclamo.get('grupo', '')}
            Palabras clave: {palabras_clave}
            Descripción:
            {reclamo.get('descripcion', '')}
            Conceptos:
            {conceptos}""".strip()


def parse_md_to_chunks(md_text):
    lines = md_text.splitlines()
    documento = ""
    seccion = ""
    categoria = None
    subcategoria = None
    grupo = None
    chunks = []
    metadata = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("# documento:"):
            documento = stripped.split(":", 1)[1].strip()
            i += 1
            continue
        if stripped.startswith("# seccion:"):
            seccion = stripped.split(":", 1)[1].strip()
            i += 1
            continue
        if stripped.startswith("## COMERCIALES"):
            categoria = "COMERCIALES"
            i += 1
            continue
        if stripped.startswith("## OPERACIONALES"):
            categoria = "OPERACIONALES"
            i += 1
            continue
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            subcategoria = stripped[4:].strip()
            i += 1
            continue
        if stripped.startswith("#### "):
            grupo = stripped[5:].strip()
            i += 1
            continue
        if stripped.startswith("- tipo:"):
            tipo = stripped.replace("- tipo:", "").strip()
            descripcion = ""
            palabras_clave = []
            i += 1
            while i < len(lines):
                next_line = lines[i].rstrip()
                next_stripped = next_line.strip()
                if next_stripped.startswith("palabras_clave:"):
                    i += 1
                    while i < len(lines):
                        kw_line = lines[i].rstrip()
                        kw_stripped = kw_line.strip()
                        if kw_stripped.startswith("- "):
                            palabras_clave.append(kw_stripped[2:].strip())
                            i += 1
                            continue
                        if kw_stripped.startswith("descripcion:") or kw_stripped.startswith("- tipo:") or kw_stripped.startswith("## ") or kw_stripped.startswith("### ") or kw_stripped.startswith("#### "):
                            break
                        if not kw_stripped:
                            i += 1
                            continue
                        i += 1
                    continue
                if next_stripped.startswith("descripcion:"):
                    i += 1
                    continue
                if next_line.startswith("    ") or next_line.startswith("\t"):
                    if next_stripped and next_stripped != "|":
                        if descripcion:
                            descripcion += " " + next_stripped
                        else:
                            descripcion = next_stripped
                    i += 1
                    continue
                if next_stripped.startswith("- tipo:"):
                    break
                if next_stripped.startswith("## ") or next_stripped.startswith("### ") or next_stripped.startswith("#### "):
                    break
                if not next_stripped:
                    i += 1
                    continue
                i += 1
            descripcion = clean(descripcion)
            reclamo = {
                "Documento": documento,
                "Seccion": seccion,
                "categoria": categoria,
                "subcategoria": subcategoria,
                "grupo": grupo,
                "tipo": tipo,
                "descripcion": descripcion,
                "palabras_clave": palabras_clave,
                "conceptos": extract_concepts(descripcion + " " + " ".join(palabras_clave))
            }
            chunks.append(build_chunk(reclamo))
            metadata.append(reclamo)
            continue
        i += 1
    return chunks, metadata
