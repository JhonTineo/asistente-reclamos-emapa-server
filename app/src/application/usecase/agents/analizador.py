import os
import re
import spacy
import time
import logging
from app.src.application.services.rag.embeddings import EmbeddingService
from app.src.application.services.rag.qdrant_store import QdrantStore

logger = logging.getLogger("agent.clasificador")


def _normalizar_texto_reclamo(texto: str) -> str:
    """Normaliza el texto del reclamo antes del análisis NLP.

    Separa palabras clave del dominio que a veces vienen pegadas
    (por ejemplo, 'MEDIDOREL' -> 'MEDIDOR EL').
    """
    texto = texto.strip()
    # Palabras clave del dominio que suelen aparecer pegadas
    palabras = [
        "medidor", "recibo", "factura", "facturación", "facturacion",
        "consumo", "suministro", "lectura", "conexión", "conexion",
        "servicio", "pago", "cobro", "tarifa", "alcantarillado",
        "mantenimiento", "reubicación", "reubicacion", "instalación",
        "instalacion", "fuga", "filtración", "filtracion", "atoro",
        "desagüe", "desague", "agua"
    ]
    for palabra in palabras:
        # Separa palabra si está seguida de otra letra (minúscula o con tilde)
        patron = re.compile(rf"({re.escape(palabra)})([a-záéíóúñ])", re.IGNORECASE)
        texto = patron.sub(r"\1 \2", texto)
    return texto


class AnalizadorAgent:

    DOMINIO = {
        "medidor": "MEDIDOR",
        "lectura": "LECTURA",
        "factura": "FACTURA",
        "facturación": "FACTURA",
        "recibo": "RECIBO",
        "pago": "PAGO",
        "pagado": "PAGO",
        "consumo": "CONSUMO",
        "consumir": "CONSUMO",
        "suministro": "SUMINISTRO",
        "conexion": "CONEXION",
        "conexión": "CONEXION",
        "conectar": "CONEXION",
        "instalacion": "INSTALACION",
        "instalación": "INSTALACION",
        "instalar": "INSTALACION",
        "servicio": "SERVICIO",
        "unidad": "UNIDAD",
        "tarifa": "TARIFA",
        "cobro": "COBRO",
        "cobrar": "COBRO",
        "alcantarillado": "ALCANTARILLADO",
        "desague": "ALCANTARILLADO",
        "desagüe": "ALCANTARILLADO",
        "fuga": "FUGA",
        "filtracion": "FILTRACION",
        "filtración": "FILTRACION",
        "mantenimiento": "MANTENIMIENTO",
        "reubicacion": "REUBICACION",
        "reubicación": "REUBICACION",
        "factibilidad": "FACTIBILIDAD",
        "trámite": "TRAMITE",
        "tramite": "TRAMITE"
    }

    KEYWORDS_RECLAMO = {
        # Frases específicas de tipos de reclamo (evita palabras sueltas
        # como 'consumo', 'recibo' o 'cobro' que aparecen en muchos reclamos)
        "consumo medido", "consumo promedio", "asignación de consumo",
        "no facturado oportunamente", "servicio cerrado", "usuario anterior",
        "cruce de suministros", "pago no procesado", "tipo de tarifa",
        "conceptos emitidos", "unidades de uso", "instalación no realizada",
        "informe de factibilidad", "no admite trámite", "servicio no corresponde",
        "filtración de aguas externas", "fugas en conexión domiciliaria",
        "negativa a mantenimiento", "atoro en conexión", "negativa a reubicación",
        # Palabras clave compuestas del dominio
        "lectura del medidor", "consumo según medidor", "medición real",
        "m3 registrados", "facturación por medidor", "lectura actual",
        "lectura actual del medidor", "lectura menor a la facturada",
        "medidor no llega a la lectura del recibo", "consumo menor al medido",
        "discrepancia de lectura", "error de lectura", "revisar medidor",
        "facturación por promedio", "consumo estimado", "monto facturado",
        "mal calculado", "cálculo incorrecto",
        "volumen facturado excesivo", "unidades de uso excesivas",
        "número de unidades mayor", "tarifa equivocada", "asignación incorrecta",
        "cobro atrasado", "facturación tardía", "deuda antigua",
        "sin conexión", "conexión cerrada", "servicio no brindado", "inactivo",
        "no tengo agua", "no recibo servicio", "no tengo conexión", "se me facturó sin tener servicio",
        "anterior titular", "cambio de titular", "deuda anterior",
        "confusión de suministro", "suministro equivocado", "medidor cruzado",
        "facturación de otro suministro",
        "pago no registrado", "pagado dos veces", "doble cobro", "cobro repetido",
        "pago duplicado", "recibo duplicado", "vuelven a cobrar",
        "cobro por pago ya realizado",
        "categoría tarifaria", "recategorización", "cambio de categoría", "tarifa no corresponde",
        "cargos indebidos", "conceptos indebidos", "cobro de alcantarillado",
        "cargos de alcantarillado",
        "cargos que no corresponden", "conceptos que no corresponden",
        "servicios colaterales", "cargos no facturables",
        "exceso de unidades", "cantidad de unidades", "predio con más unidades",
        "plazo vencido", "demora en instalación", "no instalaron",
        "desacuerdo con factibilidad", "condicionamientos técnicos", "condicionamientos administrativos",
        "solicitud rechazada", "trámite no admitido", "rechazo de solicitud",
        "condiciones del servicio", "servicio prestado no responde",
        "aguas externas", "infiltración", "agua externa en predio", "filtración hacia predio",
        "fuga de agua", "tubería rota", "pérdida de agua", "conexión domiciliaria con fuga",
        "deterioro de caja de medidor", "daño de conexión domiciliaria", "no quieren reparar",
        "ampliación de diámetro", "aumento de diámetro", "mayor diámetro", "diámetro de conexión",
        "alcantarillado atorado", "desagüe taponado", "taponamiento de alcantarillado",
        "negativa a mantenimiento de alcantarillado", "deterioro de caja de registro",
        "daño de conexión domiciliaria de alcantarillado", "no quieren reparar alcantarillado",
        "ampliación de diámetro de alcantarillado", "aumento de diámetro de alcantarillado",
        "mayor diámetro de alcantarillado", "diámetro de conexión de alcantarillado",
        "reubicación de conexión", "traslado de conexión", "no quieren reubicar",
        "reubicar", "reubiquen",
        "reubicar conexión de agua potable", "reubiquen conexión de agua potable",
        "reubicación de conexión de agua potable", "traslado de conexión de agua potable",
        "no quieren reubicar agua potable",
        "reubicar conexión de alcantarillado", "reubiquen conexión de alcantarillado",
        "reubicación de conexión de alcantarillado", "traslado de conexión de alcantarillado",
        "no quieren reubicar alcantarillado",
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

    # Palabras sueltas de menor poder discriminativo; se usan como refuerzo
    # en la consulta de embeddings y con menor peso en el reranking.
    # Se omiten términos muy genéricos como 'recibo' o 'cobro' que aparecen
    # en la mayoría de reclamos comerciales y generan falsos positivos.
    KEYWORDS_DEBILES = {
        "medidor", "factura", "facturación", "consumo",
        "tarifa", "alcantarillado", "fuga",
        "conexión", "servicio", "suministro", "lectura", "cargos"
    }

    def _extraer_keywords(self, texto: str):
        """Extrae palabras clave del detalle usando lexicon de dominio.

        Separa frases específicas (fuertes) de palabras sueltas (débiles)
        para evitar falsos positivos con términos muy genéricos.
        """
        texto_lower = texto.lower()
        fuertes = []
        for kw in self.KEYWORDS_RECLAMO:
            if kw.lower() in texto_lower:
                fuertes.append(kw)
        debiles = [k for k in self.KEYWORDS_DEBILES if k in texto_lower]
        return {"fuertes": list(set(fuertes)), "debiles": list(set(debiles))}

    def _keyword_overlap_score(self, query_keywords, item_keywords):
        """Calcula un score de solapamiento entre palabras clave de la consulta y del tipo.

        Permite coincidencias parciales controladas para capturar variaciones como
        'fuga' vs 'fuga de agua' o 'conexión domiciliaria' vs 'fugas en conexión domiciliaria'.

        Las palabras clave fuertes (frases) tienen peso completo; las débiles
        (palabras sueltas) contribuyen la mitad.
        """
        fuertes = query_keywords.get("fuertes", [])
        debiles = query_keywords.get("debiles", [])
        if (not fuertes and not debiles) or not item_keywords:
            return 0.0

        item_set = {k.lower().strip() for k in item_keywords}

        def _coincide(q, it):
            if q == it:
                return True
            if it in q:
                # La keyword del tipo aparece textualmente en el detalle
                return True
            if q in it:
                # La query está contenida en la keyword del tipo; permitir si
                # la query es una frase o el item no es excesivamente más largo.
                len_q = len(q.split())
                len_it = len(it.split())
                return len_q >= 2 or len_it <= len_q + 2
            return False

        def _score_set(query_set, peso_palabra):
            peso_total = 0.0
            coincidencias = 0
            for q in query_set:
                q_norm = q.lower().strip()
                for it in item_set:
                    if _coincide(q_norm, it):
                        # Peso según la palabra/frase más larga que coincide
                        peso = max(len(q_norm.split()), len(it.split()))
                        peso_total += peso * peso_palabra
                        coincidencias += 1
                        break
            return peso_total, coincidencias

        peso_fuertes, coin_fuertes = _score_set(fuertes, 1.0)
        peso_debiles, coin_debiles = _score_set(debiles, 0.5)

        total_coincidencias = coin_fuertes + coin_debiles
        if total_coincidencias == 0:
            return 0.0

        # Normalizar por el número de keywords de la consulta
        query_count = len(fuertes) + len(debiles)
        return (peso_fuertes + peso_debiles) / (query_count + len(item_set))

    def _clasificar(self, conceptos, acciones, numeros, dominio, detalle, keywords):
        embedder = EmbeddingService()

        todas_keywords = keywords.get("fuertes", []) + keywords.get("debiles", [])
        keywords_repetidas = ", ".join(todas_keywords[:12]) if todas_keywords else ""
        partes = [
            f"Detalle del reclamo: {detalle}",
            f"Problema relacionado con: {', '.join(conceptos[:8])}",
            f"Acciones del usuario: {', '.join(acciones[:5])}",
            f"Dominio: {', '.join(dominio)}",
            f"Palabras clave: {keywords_repetidas}",
            f"Términos relevantes: {keywords_repetidas}",
        ]
        consulta = " ".join([p for p in partes if p.split(": ", 1)[-1]])

        logger.info(f"Consulta para embeddings: {consulta}")
        vector = embedder.encode(consulta)

        qdrant = QdrantStore()
        resultados = qdrant.search(
            vector,
            top_k=5,
            collection_name="anexo1_tipos_reclamo"
        )

        if not resultados:
            return {"tipo": "No determinado", "descripcion": None, "score": 0.0}

        # Re-ranking por solapamiento de palabras clave fuertes.
        # Solo se usa como desempate cuando los scores de embedding están
        # muy cercanos, para evitar que palabras sueltas desplacen al
        # candidato con mejor embedding.
        scored = []
        for r in resultados:
            payload = r["payload"]
            item_keywords = payload.get("palabras_clave", [])
            overlap_fuertes = self._keyword_overlap_score(
                {"fuertes": keywords.get("fuertes", []), "debiles": []},
                item_keywords
            )
            scored.append({
                "tipo": payload.get("tipo"),
                "descripcion": payload.get("descripcion"),
                "emb_score": r["score"],
                "overlap": overlap_fuertes,
            })

        # Ordenar primero por embedding score
        scored.sort(key=lambda x: x["emb_score"], reverse=True)
        mejor_emb = scored[0]

        # Considerar candidatos a menos de 0.02 del mejor embedding score
        umbral_empate = 0.02
        candidatos = [s for s in scored if mejor_emb["emb_score"] - s["emb_score"] <= umbral_empate]

        # Entre los candidatos cercanos, elegir el de mayor overlap de keywords fuertes
        mejor = max(candidatos, key=lambda x: (x["overlap"], x["emb_score"]))

        if mejor and mejor["emb_score"] > 0.45:
            return {
                "tipo": mejor["tipo"],
                "descripcion": mejor["descripcion"],
                "score": mejor["emb_score"],
            }

        return {"tipo": "No determinado", "descripcion": None, "score": 0.0}


    def run(self, detalle):
        t0 = time.perf_counter()
        texto_normalizado = _normalizar_texto_reclamo(detalle)
        texto = texto_normalizado.lower()
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

        keywords = self._extraer_keywords(texto)
        clasificacion = self._clasificar(conceptos, acciones, numeros, dominio, detalle, keywords)
        t4 = time.perf_counter()
        logger.info(f"Tiempo clasificación: {t4 - t3:.4f} segundos")

        return {
            "categoria_probable": clasificacion["tipo"],
            "descripcion": clasificacion["descripcion"],
            "score": clasificacion["score"]
        }