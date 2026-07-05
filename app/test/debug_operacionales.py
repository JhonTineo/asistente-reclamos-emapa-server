import sys
sys.path.insert(0, 'D:\\JhonTineo\\Documents\\GitHub\\asistente-reclamos-emapa-server')
from app.src.application.usecase.agents.analizador import AnalizadorAgent
from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore

agent = AnalizadorAgent()

detalles = [
    "Quiero que reubiquen mi conexión domiciliaria porque ya tengo estudio de factibilidad favorable.",
    "Me cobraron cargos de alcantarillado que no corresponden.",
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

    todas = keywords.get("fuertes", []) + keywords.get("debiles", [])
    keywords_repetidas = ", ".join(todas[:12]) if todas else ""
    partes = [
        f"Detalle del reclamo: {detalle}",
        f"Problema relacionado con: {', '.join(conceptos[:8])}",
        f"Acciones del usuario: {', '.join(acciones[:5])}",
        f"Dominio: {', '.join(dominio)}",
        f"Palabras clave: {keywords_repetidas}",
        f"Términos relevantes: {keywords_repetidas}",
    ]
    consulta = " ".join([p for p in partes if p.split(": ", 1)[-1]])
    print(f"Consulta: {consulta}")

    embedder = EmbeddingService()
    vector = embedder.encode(consulta)
    qdrant = QdrantStore()
    resultados = qdrant.search(vector, top_k=5, collection_name="anexo1_tipos_reclamo")

    for r in resultados:
        payload = r["payload"]
        item_keywords = payload.get("palabras_clave", [])
        overlap = agent._keyword_overlap_score(keywords, item_keywords)
        tipo = payload.get("tipo", "")[:40]
        print(f"  {tipo:40} | emb={r['score']:.4f} | overlap={overlap:.4f}")
