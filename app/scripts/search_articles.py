import logging
from typing import List, Dict

from sentence_transformers import SentenceTransformer

from app.tools.vector_db import QdrantStore

logger = logging.getLogger(__name__)

MODEL_NAME = "intfloat/multilingual-e5-base"

embedder = SentenceTransformer(MODEL_NAME)

qdrant = QdrantStore(
    dim=embedder.get_sentence_embedding_dimension()
)


def retrieve_top_articles(
    complaint_text: str,
    top_k: int = 5
) -> List[Dict]:

    if not complaint_text.strip():
        return []

    query = f"query: {complaint_text}"

    query_embedding = embedder.encode(
        query,
        normalize_embeddings=True
    )

    results = qdrant.search(
        vector=query_embedding.tolist(),
        top_k=top_k
    )

    formatted_results = []

    for rank, result in enumerate(results, start=1):

        payload = result["payload"]

        formatted_results.append({
            "rank": rank,
            "score": round(result["score"], 4),
            "article": payload.get("article"),
            "numeral": payload.get("numeral"),
            "norma": payload.get("norma"),
            "texto": payload.get("text"),
            "source": payload.get("source")
        })

    return formatted_results


if __name__ == "__main__":

    complaint = """
    La empresa prestadora no respondió mi solicitud de
    factibilidad dentro del plazo establecido y tampoco
    entregó el informe técnico correspondiente.
    """

    results = retrieve_top_articles(
        complaint,
        top_k=5
    )

    print("\nTOP ARTÍCULOS RELACIONADOS\n")

    for r in results:

        print("=" * 80)
        print(f"Ranking : {r['rank']}")
        print(f"Score   : {r['score']}")
        print(f"Artículo: {r['article']}")
        print(f"Numeral : {r['numeral']}")
        print(f"Norma   : {r['norma']}")
        print(f"Fuente  : {r['source']}")
        print("\nTexto:")
        print(r["texto"][:1000])
        print()