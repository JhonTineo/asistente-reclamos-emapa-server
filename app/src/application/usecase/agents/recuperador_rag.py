import logging
from app.src.application.ports.vector_db_port import PuertoBaseVectorial

logger = logging.getLogger("agent.recuperador_rag")


class RecuperadorRAGAgent():
    role = "recuperador_rag"

    def __init__(self, store: PuertoBaseVectorial, model: str | None = None, collection: str | None = None):
        super().__init__(model=model)
        self.store = store

    def run(self, input_data: dict) -> dict:
        query_embedding = input_data.get("embedding")
        top_k = input_data.get("top_k", 5)

        if query_embedding is None:
            # Accept a text query and compute embedding via model if available
            raise ValueError("Se requiere 'embedding' en input_data para el recuperador RAG")

        results = self.store.search(query_embedding, top_k=top_k)

        logger.info("Recuperador: devolviendo %d resultados", len(results))
        return {"retrieved": results}
