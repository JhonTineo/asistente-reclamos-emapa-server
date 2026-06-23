import os
import spacy
import time
import logging
from app.src.rag.embeddings import EmbeddingService
from app.src.rag.qdrant_store import QdrantStore

logger = logging.getLogger("agent.clasificador")


class AnalizadorAgent:

    DOMINIO = {
        "medidor": "MEDIDOR",
        "lectura": "LECTURA",
        "factura": "FACTURA",
        "recibo": "RECIBO",
        "pago": "PAGO",
        "consumo": "CONSUMO",
        "suministro": "SUMINISTRO",
        "conexion": "CONEXION",
        "conexión": "CONEXION",
        "servicio": "SERVICIO",
        "unidad": "UNIDAD"
    }

    def __init__(self):
        spacy_model = os.getenv(
            "SPACY_MODEL",
            "es_core_news_md"
        )
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            self.nlp = spacy.blank("es")


    def _extraer_conceptos(self, doc):
        conceptos = []
        for token in doc:
            if token.pos_ == "NOUN":
                conceptos.append(token.lemma_)
        return list(set(conceptos))


    def _extraer_acciones(self, doc):
        acciones = []
        for token in doc:
            if token.pos_ == "VERB":
                acciones.append(token.lemma_)
        return list(set(acciones))


    def _extraer_numeros(self, doc):
        numeros = []
        for token in doc:
            if token.pos_ == "NUM":
                numeros.append(token.text)
        return numeros


    def _extraer_entidades(self, doc):
        entidades = []
        for ent in doc.ents:
            entidades.append(
                {
                    "texto": ent.text,
                    "tipo": ent.label_
                }
            )
        return entidades


    def _extraer_conceptos_dominio(self, doc):
        encontrados = []
        for token in doc:
            lemma = token.lemma_
            if lemma in self.DOMINIO:
                encontrados.append(
                    self.DOMINIO[lemma]
                )
        return list(set(encontrados))

    def _clasificar(self, conceptos, acciones, numeros, dominio, detalle):
        

        embedder = EmbeddingService()
        consulta = f"Problema relacionado con: {', '.join(conceptos[:5])}"
        consulta += f". Acciones del usuario: {', '.join(acciones[:3])}"
        consulta += f". Dominio: {', '.join(dominio)}"
        print(f"Consulta para embeddings: {consulta}")
        vector = embedder.encode(consulta)

        qdrant = QdrantStore()
        resultados = qdrant.search(
            vector,
            top_k=3,
            collection_name="anexo1_tipos_reclamo"
        )

        if resultados and resultados[0]["score"] > 0.5:
            payload = resultados[0]["payload"]
            return {
                "tipo": payload.get("tipo"),
                "descripcion": payload.get("descripcion"),
                "score": resultados[0]["score"]

            }

        return {"tipo": "No determinado", "descripcion": None, "score": 0.0}


    def run(self, detalle):
        t0 = time.perf_counter()
        texto = detalle.lower()
        t1 = time.perf_counter()
        logger.info(f"Tiempo conversion a minusculas: {t1 - t0:.4f} segundos")
        doc = self.nlp(texto)
        t2 = time.perf_counter()
        logger.info(f"Tiempo procesamiento NLP: {t2 - t1:.4f} segundos")

        conceptos = self._extraer_conceptos(doc)
        acciones = self._extraer_acciones(doc)
        numeros = self._extraer_numeros(doc)
        entidades = self._extraer_entidades(doc)
        dominio = self._extraer_conceptos_dominio(doc)
        t3 = time.perf_counter()
        logger.info(f"Tiempo extracción de información: {t3 - t2:.4f} segundos")

        clasificacion = self._clasificar(conceptos, acciones, numeros, dominio, detalle)
        t4 = time.perf_counter()
        logger.info(f"Tiempo clasificación: {t4 - t3:.4f} segundos")

        return {
            "categoria_probable": clasificacion["tipo"],
            "descripcion": clasificacion["descripcion"],
            "score": clasificacion["score"]
        }