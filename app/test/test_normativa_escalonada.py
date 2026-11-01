# -*- coding: utf-8 -*-
"""Búsqueda escalonada reclamos -> calidad en FundamentacionNormativaAgent.

Sin Ollama, sin Qdrant y sin LLM: el retriever y el router del LLM son dobles.

    python -m pytest app/test/test_normativa_escalonada.py -v
"""

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

import pytest

from app.src.application.usecase.agents import fundamentacion_normativa as mod
from app.src.core.model.informe_atencion import ProblemaNormado


def _punto(article, numeral, score, texto="texto"):
    return {"id": f"{article}-{numeral}", "score": score,
            "payload": {"article": article, "numeral": numeral, "text": texto}}


class RetrieverFalso:
    """Devuelve lo que la prueba tenga cargado para cada colección y registra
    el orden en que se consultó."""
    por_coleccion: dict = {}
    consultas: list = []

    def __init__(self, store):
        self.store = store

    def retrieve(self, query, top_k=5, collection_name=None):
        RetrieverFalso.consultas.append((collection_name, query))
        return [dict(p) for p in RetrieverFalso.por_coleccion.get(collection_name, [])][:top_k]


class StoreFalso:
    def __init__(self, existentes):
        self.existentes = existentes

    def collection_exists(self, nombre):
        return nombre in self.existentes


class RouterFalso:
    """Responde según la colección que aparezca en el prompt: así la prueba
    controla qué norma 'argumenta' y cuál abstiene."""
    def __init__(self, aplica_en):
        self.aplica_en = aplica_en
        self.prompts = []

    def generar_json(self, mensajes, modelo_id=None):
        prompt = mensajes[0].contenido + mensajes[1].contenido
        self.prompts.append(prompt)
        norma = "calidad" if "Reglamento de Calidad" in prompt else "reclamos"
        if norma in self.aplica_en:
            return json.dumps({"aplica": True, "accion": "refacturar por promedio histórico",
                               "base_legal": "Art. 92.3", "justificacion": "x"})
        return json.dumps({"aplica": False, "accion": "no_determinable", "base_legal": None})


@pytest.fixture(autouse=True)
def _doble(monkeypatch):
    RetrieverFalso.consultas = []
    RetrieverFalso.por_coleccion = {}
    monkeypatch.setattr(mod, "Retriever", RetrieverFalso)
    monkeypatch.setattr(mod.settings, "normativa_fuentes", "sunass_reclamos,sunass_reglamento")
    monkeypatch.setattr(mod.settings, "normativa_umbral_score", 0.5)


def _agente(router, existentes=("sunass_reclamos", "sunass_reglamento")):
    return mod.FundamentacionNormativaAgent(StoreFalso(set(existentes)), router, model="m")


def _problema():
    return ProblemaNormado(tipo="fugas", detalle="Fuga no visible: detectada en la inspección")


def test_si_reclamos_argumenta_no_se_consulta_calidad_para_el_llm():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterFalso(aplica_en={"reclamos"})
    p = _agente(router).fundamentar(_problema(), "facturación excesiva")
    assert p.base_legal == "Art. 92.3 (Reglamento de Reclamos)"
    assert [a["coleccion"] for a in p.articulos] == ["sunass_reclamos"]
    assert len(router.prompts) == 1
    assert RetrieverFalso.consultas[0][0] == "sunass_reclamos"


def test_si_reclamos_no_alcanza_se_escala_a_calidad():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterFalso(aplica_en={"calidad"})
    p = _agente(router).fundamentar(_problema(), "facturación excesiva")
    assert len(router.prompts) == 2                       # reclamos abstuvo, calidad argumentó
    assert [a["norma_corta"] for a in p.articulos] == ["Reglamento de Calidad"]
    assert p.base_legal == "Art. 92.3 (Reglamento de Calidad)"
    assert [c for c, _ in RetrieverFalso.consultas] == ["sunass_reclamos", "sunass_reglamento"]


def test_si_reclamos_no_supera_el_umbral_ni_se_le_pregunta_al_llm():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.3)],       # bajo el umbral
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterFalso(aplica_en={"calidad"})
    p = _agente(router).fundamentar(_problema())
    assert len(router.prompts) == 1                       # solo calidad
    assert p.articulos[0]["coleccion"] == "sunass_reglamento"


def test_si_ninguna_norma_regula_el_hallazgo_no_se_cita_nada():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    p = _agente(RouterFalso(aplica_en=set())).fundamentar(_problema())
    assert p.base_legal is None
    assert p.accion.startswith("No corresponde")


def test_si_la_coleccion_de_reclamos_aun_no_existe_se_usa_calidad():
    RetrieverFalso.por_coleccion = {"sunass_reglamento": [_punto("92", "92.3", 0.9)]}
    router = RouterFalso(aplica_en={"calidad"})
    p = _agente(router, existentes=("sunass_reglamento",)).fundamentar(_problema())
    assert [c for c, _ in RetrieverFalso.consultas] == ["sunass_reglamento"]
    assert p.base_legal == "Art. 92.3 (Reglamento de Calidad)"


def test_flujo_en_dos_fases_del_streaming_tambien_escala():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    agente = _agente(RouterFalso(aplica_en={"calidad"}))
    p = _problema()
    articulos = agente.fundamentar_articulos(p, "motivo")           # evento "articulos"
    assert p.articulos[0]["coleccion"] == "sunass_reclamos"
    agente.fundamentar_interpretacion(p, articulos, "", "motivo")   # evento "fundamentacion"
    assert p.articulos[0]["coleccion"] == "sunass_reglamento"       # el evento final lleva los de calidad


def test_cada_norma_se_consulta_con_su_propia_query():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    _agente(RouterFalso(aplica_en={"calidad"})).fundamentar(_problema())
    q_reclamos, q_calidad = (q for _, q in RetrieverFalso.consultas)
    assert "inspección interna y externa como medio de prueba" in q_reclamos
    assert "diferencia de lecturas" in q_calidad


class RouterMarcarFalso:
    """Para `marcar_aplica` (flujo vigente): devuelve la lista de índices que
    aplican según la norma que aparezca en el listado de artículos del prompt."""
    def __init__(self, aplica_en):
        self.aplica_en = aplica_en
        self.prompts = []

    def generar_json(self, mensajes, modelo_id=None):
        prompt = mensajes[0].contenido + mensajes[1].contenido
        self.prompts.append(prompt)
        norma = "calidad" if "del Reglamento de Calidad" in prompt else "reclamos"
        return "[0]" if norma in self.aplica_en else "[]"


def test_buscar_y_marcar_se_queda_en_reclamos_si_un_articulo_aplica():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterMarcarFalso(aplica_en={"reclamos"})
    arts = _agente(router).buscar_y_marcar(_problema(), "", "motivo")
    assert [(a["coleccion"], a["aplica"]) for a in arts] == [("sunass_reclamos", True)]
    assert len(router.prompts) == 1
    assert [c for c, _ in RetrieverFalso.consultas] == ["sunass_reclamos"]   # calidad ni se consulta


def test_buscar_y_marcar_escala_a_calidad_si_en_reclamos_ninguno_aplica():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterMarcarFalso(aplica_en={"calidad"})
    arts = _agente(router).buscar_y_marcar(_problema(), "", "motivo")
    # El frontend ve lo evaluado en la norma prioritaria (sin aplicar) y con cuál se argumentó.
    assert [(a["norma_corta"], a["aplica"]) for a in arts] == [
        ("Reglamento de Reclamos", False), ("Reglamento de Calidad", True),
    ]
    assert "del Reglamento de Reclamos" in router.prompts[0]
    assert [c for c, _ in RetrieverFalso.consultas] == ["sunass_reclamos", "sunass_reglamento"]


def test_buscar_y_marcar_pasa_directo_a_calidad_si_reclamos_no_supera_el_umbral():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.3)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    router = RouterMarcarFalso(aplica_en={"calidad"})
    arts = _agente(router).buscar_y_marcar(_problema(), "", "motivo")
    assert [(a["coleccion"], a["aplica"]) for a in arts] == [("sunass_reglamento", True)]
    assert len(router.prompts) == 1


def test_buscar_y_marcar_si_ninguna_norma_aplica_devuelve_lo_evaluado_sin_aplica():
    RetrieverFalso.por_coleccion = {
        "sunass_reclamos": [_punto("14", "14.2", 0.8)],
        "sunass_reglamento": [_punto("92", "92.3", 0.9)],
    }
    arts = _agente(RouterMarcarFalso(aplica_en=set())).buscar_y_marcar(_problema(), "", "motivo")
    assert len(arts) == 2 and not any(a["aplica"] for a in arts)


def test_buscar_y_marcar_sin_colecciones_o_sin_resultados_devuelve_vacio():
    assert _agente(RouterMarcarFalso(aplica_en=set()), existentes=()).buscar_y_marcar(_problema()) == []
    RetrieverFalso.por_coleccion = {"sunass_reclamos": [_punto("14", "14.2", 0.1)]}
    assert _agente(RouterMarcarFalso(aplica_en=set())).buscar_y_marcar(_problema()) == []


def test_todos_los_tipos_de_problema_tienen_consulta_canonica():
    from app.src.application.services.pre_proces import problemas_normalizer as pn
    tipos = (set(pn.GRUPOS_TARJETA) | set(pn.GRUPOS_SALDO) | set(pn.GRUPOS_RECORD)
             | {"mesesCortados", "reclamosPrevios", "atipico", "fugas", "equipo"})
    assert tipos - set(mod.CONSULTA_POR_TIPO) == set()
    assert tipos - set(mod.CONSULTA_RECLAMOS_POR_TIPO) == set()
