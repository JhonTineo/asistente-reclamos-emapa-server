import os
import re

import spacy


class AnalizadorAgent:

    def __init__(self):
        spacy_model = os.getenv("SPACY_MODEL", "es_core_news_sm")
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            self.nlp = spacy.blank("es")

    def run(self, detalle: str) -> dict:
        doc = self.nlp(detalle)

        tipo = self._extract_tipo(detalle.lower())
        servicio = self._extract_servicio(detalle.lower())
        hechos = self._extract_hechos(doc)
        evidencias = self._extract_evidencias(detalle.lower())

        return {
            "tipo": tipo,
            "servicio": servicio,
            "hechos": hechos,
            "evidencias": evidencias,
        }

    def _extract_tipo(self, text: str) -> str:
        categorias = {
            "cobro": ["cobro", "factura", "recibo", "tarifa"],
            "suministro": ["suministro", "agua", "corte", "reconexion"],
            "calidad": ["olor", "turbiedad", "color", "sabor"],
            "medidor": ["medidor", "lectura", "exceso de consumo"],
            "inspeccion": ["inspección", "inspeccion", "visita"],
        }

        for categoria, palabras in categorias.items():
            if any(palabra in text for palabra in palabras):
                return categoria

        return "otro"

    def _extract_servicio(self, text: str) -> str:
        servicios = {
            "agua potable": ["agua potable", "agua", "potable"],
            "alcantarillado": ["alcantarillado", "desagüe", "drenaje"],
            "facturacion": ["factura", "cobro", "recibo", "tarifa"],
            "suministro": ["suministro", "conexión", "corte"],
        }

        for servicio, palabras in servicios.items():
            if any(palabra in text for palabra in palabras):
                return servicio

        return "general"

    def _extract_hechos(self, doc) -> list[str]:
        hechos = []

        for sent in doc.sents:
            texto = sent.text.strip()
            if len(texto) > 30:
                hechos.append(texto)

        if not hechos:
            hechos = [sent.text.strip() for sent in doc.sents if sent.text.strip()]

        return hechos

    def _extract_evidencias(self, text: str) -> list[str]:
        evidencias = []
        patrones = [
            r"adjunto[s]?", r"comprobante[s]?", r"factura[s]?", r"foto[s]?", r"documento[s]?", r"mensaje[s]?", r"correo[s]?"
        ]

        for patron in patrones:
            coincidencias = re.findall(patron, text)
            if coincidencias:
                evidencias.extend(coincidencias)

        return list(dict.fromkeys(evidencias))