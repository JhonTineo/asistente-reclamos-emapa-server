import sys
sys.path.insert(0, 'D:\\JhonTineo\\Documents\\GitHub\\asistente-reclamos-emapa-server')
from app.src.application.usecase.agents.analizador import AnalizadorAgent

agent = AnalizadorAgent()

detalles = [
    "Tengo una fuga en la conexión domiciliaria.",
    "Me cobraron cargos de alcantarillado que no corresponden.",
    "No estoy conforme con el cobro de los recibos del 2025, ya que mis consumos son de 23 m3 aproximadamente.",
]

for detalle in detalles:
    print(f"\nDetalle: {detalle}")
    texto = detalle.lower()
    doc = agent.nlp(texto)
    conceptos = agent._extraer_conceptos(doc)
    acciones = agent._extraer_acciones(doc)
    dominio = agent._extraer_conceptos_dominio(doc)
    keywords = agent._extraer_keywords(texto)
    print(f"Conceptos: {conceptos}")
    print(f"Acciones: {acciones}")
    print(f"Dominio: {dominio}")
    print(f"Keywords: {keywords}")

    # Simular consulta y buscar top 5
    from app.src.application.services.rag.embeddings import EmbeddingService
    from app.src.application.services.rag.qdrant_store import QdrantStore

    keywords_repetidas = ", ".join(keywords[:10]) if keywords else ""
    partes = [
        f"Detalle del reclamo: {detalle}",
        f"Problema relacionado con: {', '.join(conceptos[:8])}",
        f"Acciones del usuario: {', '.join(acciones[:5])}",
        f"Dominio: {', '.join(dominio)}",
        f"Palabras clave: {keywords_repetidas}",
        f"Términos relevantes: {keywords_repetidas}",
    ]
    consulta = " ".join([p for p in partes if p.split(": ", 1)[-1]])
    print(f"Consulta: {consulta[:200]}...")

    embedder = EmbeddingService()
    vector = embedder.encode(consulta)
    qdrant = QdrantStore()
    resultados = qdrant.search(vector, top_k=5, collection_name="anexo1_tipos_reclamo")

    for r in resultados:
        payload = r["payload"]
        item_keywords = payload.get("palabras_clave", [])
        overlap = agent._keyword_overlap_score(keywords, item_keywords)
        score_final = r["score"] + 0.25 * overlap
        print(f"  {payload.get('tipo')[:40]:40} | emb={r['score']:.4f} | overlap={overlap:.4f} | final={score_final:.4f}")
