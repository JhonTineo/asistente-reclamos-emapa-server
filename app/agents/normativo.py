from app.rag.retriever import RegulationRetriever


class NormativoAgent:

    def __init__(self):
        self.retriever = RegulationRetriever()

    def run(self, detalle, analisis):
        query = (
            f"Tipo: {analisis.get('tipo', '')}\n"
            f"Servicio: {analisis.get('servicio', '')}\n"
            f"Hechos: {' '.join(analisis.get('hechos', []))}\n"
            f"Detalle del reclamo: {detalle}"
        )

        return self.retriever.retrieve(
            query,
            top_k=5
        )