from app.src.application.services.rag.retriever import Retriever


class NormativoAgent:

    def __init__(self):
        self.retriever = Retriever()

    def run(self, detalle, analisis):
        query = (
            f"Tipo: {analisis.get('tipo', '')}\n"
            f"Servicio: {analisis.get('servicio', '')}\n"
            f"Hechos: {' '.join(analisis.get('hechos', []))}\n"
            f"Detalle del reclamo: {detalle}"
        )

        normas_relacionadas = self.retriever.retrieve(
            collection_name="sunass_reglamento",
            query=query,
            top_k=5
        )

        return self.retriever.build_context(
            collection_name="sunass_reglamento",
            results=normas_relacionadas
        )