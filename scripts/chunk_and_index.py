import re
import os
import sys
import glob
import uuid
import logging
from typing import List

# Add parent directory to path to import app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer

from app.tools.vector_db import QdrantStore

logger = logging.getLogger("chunker")


def extract_text_from_pdf(path: str) -> str:
    doc = fitz.open(path)
    texts = []
    for page in doc:
        texts.append(page.get_text())
    return "\n".join(texts)


def split_articles(text: str) -> List[dict]:
    # Split by Spanish article headings (Artículo, ARTÍCULO, ARTICULO)
    pattern = re.compile(r"(?=(?:^|\n)\s*(ART[IÍ]CULO|Artículo|ARTICULO)\s+\d+)", re.IGNORECASE)
    parts = pattern.split(text)
    # pattern.split returns separators included; simpler approach: find all matches spans
    matches = list(re.finditer(r"(?:^|\n)\s*(ART[IÍ]CULO|Artículo|ARTICULO)\s+\d+.*", text, re.IGNORECASE))
    if not matches:
        # Fallback: return whole document as single chunk
        return [{"title": "document", "text": text}]

    articles = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title_line = m.group().strip().splitlines()[0]
        body = text[start:end].strip()
        articles.append({"title": title_line, "text": body})

    return articles


def chunk_text(text: str, chunk_size: int = 10000, overlap: int = 200) -> List[str]:
    chunks = []
    start = 0
    L = len(text)
    while start < L:
        end = min(start + chunk_size, L)
        chunk = text[start:end]
        chunks.append(chunk.strip())
        if overlap <= 0 or start == 0:
            start += chunk_size - max(overlap, 1)
        else:
            start = end - overlap
    return [c for c in chunks if c]



def index_pdf(pdf_path: str, model_name: str = "all-MiniLM-L6-v2") -> None:
    logger.info("Indexando PDF: %s", pdf_path)
    text = extract_text_from_pdf(pdf_path)
    articles = split_articles(text)

    embedder = SentenceTransformer(model_name)
    q = QdrantStore(dim=embedder.get_embedding_dimension())
    q.create_collection()

    points = []
    for art in articles:
        title = art["title"]
        body = art["text"]
        article_chunks = chunk_text(body)
        for idx, chunk in enumerate(article_chunks):
            vec = embedder.encode(chunk).tolist()
            pid = str(uuid.uuid4())
            payload = {"title": title, "source": os.path.basename(pdf_path), "chunk_index": idx, "text": chunk}
            points.append({"id": pid, "vector": vec, "payload": payload})

    # Upsert in batches
    batch_size = 128
    for i in range(0, len(points), batch_size):
        q.upsert(points[i : i + batch_size])

    logger.info("Indexado completado. Puntos subidos: %d", len(points))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    base = os.path.join(os.path.dirname(__file__), "..", "app", "storage", "files")
    base = os.path.abspath(base)
    pdfs = glob.glob(os.path.join(base, "*.pdf"))
    if not pdfs:
        logger.error("No se encontraron PDFs en %s", base)
        raise SystemExit(1)

    for p in pdfs:
        index_pdf(p)
