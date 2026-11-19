"""El paralelismo (medios y fundamentación) solo cambia CUÁNDO se ejecuta cada
cosa, no QUÉ recibe el modelo: estas pruebas fijan esa garantía."""

import asyncio
import itertools
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.src.application.services.informe.informe_store import (
    InformeAtencionStore, ORDEN_MEDIOS, ordenar_bloques,
)
from app.src.application.services.investigacion import fundamentacion_service
from app.src.application.services.llm import uso_tokens
from app.src.core.model.informe_atencion import BloqueMedio, ProblemaNormado


def _bloque(medio_id: str) -> BloqueMedio:
    return BloqueMedio(
        medio_id=medio_id, medio_nombre=medio_id, entidad={}, resumen=f"resumen {medio_id}",
        problemas=[ProblemaNormado(tipo="errorConsumo", detalle=f"hallazgo de {medio_id}",
                                   fuente=medio_id)],
    )


class OrdenDeBloquesTest(unittest.TestCase):

    MEDIOS = ["inspeccion_externa", "inspeccion_interna", "record_facturacion",
              "tarjeta_lectura", "corte_reapertura", "saldo_detalle"]

    def _registrar_en_orden(self, orden) -> list[tuple[str, str | None]]:
        store = InformeAtencionStore()
        for medio_id in orden:
            store.registrar_bloque("R-1", _bloque(medio_id), suministro="S-1")
        informe = store.obtener("R-1")
        return [(b.medio_id, b.hechos[0].id) for b in informe.bloques]

    def test_el_orden_de_llegada_no_cambia_el_informe(self):
        # En serie el front registraba los medios en el orden de MEDIOS; en
        # paralelo llegan en cualquier orden. El informe debe quedar igual.
        esperado = self._registrar_en_orden(self.MEDIOS)
        for orden in itertools.islice(itertools.permutations(self.MEDIOS), 0, None, 97):
            self.assertEqual(self._registrar_en_orden(orden), esperado, orden)

    def test_orden_igual_al_del_analisis_en_serie(self):
        self.assertEqual([m for m, _ in self._registrar_en_orden(reversed(self.MEDIOS))],
                         self.MEDIOS)

    def test_tecnico_operacional_y_desconocidos_al_final(self):
        bloques = [_bloque("tecnico_operacional"), _bloque("otro"), _bloque("tarjeta_lectura")]
        self.assertEqual([b.medio_id for b in ordenar_bloques(bloques)],
                         ["tarjeta_lectura", "tecnico_operacional", "otro"])
        self.assertEqual(ORDEN_MEDIOS[-1], "tecnico_operacional")


class _FundamentadorLento:
    """Simula el RAG: el primer hecho es el más lento, así terminan al revés."""

    def __init__(self, n: int):
        self.n = n
        self.hilos = set()
        self.concurrentes = 0
        self.max_concurrentes = 0
        self._lock = threading.Lock()
        self.parrafo_recibido = None

    def seleccionar_determinantes(self, informe):
        return list(informe.hechos)

    def buscar_articulos(self, problema, motivo, situacion):
        with self._lock:
            self.concurrentes += 1
            self.max_concurrentes = max(self.max_concurrentes, self.concurrentes)
            self.hilos.add(threading.get_ident())
        time.sleep(0.05 * (self.n - int(problema.id[-1])))
        with self._lock:
            self.concurrentes -= 1
        return [{"payload": {"article": problema.id}, "score": 0.9}]

    def marcar_aplica(self, problema, raw, clasificacion, motivo, situacion, codreclamo=None):
        return [{"article": raw[0]["payload"]["article"], "aplica": True, "codreclamo": codreclamo}]

    def redactar_parrafo(self, seleccionados, motivo, clasificacion, codreclamo=None):
        self.parrafo_recibido = [(p.id, p.articulos[0]["article"]) for p in seleccionados]
        return "párrafo"


class FundamentacionEnParaleloTest(unittest.TestCase):

    def test_articulos_en_paralelo_conservan_orden_y_asignacion(self):
        n = 4
        hechos = [ProblemaNormado(tipo="errorConsumo", detalle=f"h{i}", id=f"H-tl-0{i}")
                  for i in range(n)]
        informe = SimpleNamespace(reclamo="R-9", objetivos=[object()], bloques=[], hechos=hechos,
                                  clasificacion="A1", motivo="consumo alto",
                                  fundamentacion_normativa=None)
        store = SimpleNamespace(obtener=lambda _c: informe, invalidar_decision=lambda *_a: None)
        fake = _FundamentadorLento(n)
        request = SimpleNamespace(codreclamo="R-9", seleccion=None, clasificacion=None, modelo=None)

        with patch.object(fundamentacion_service, "informe_store", store), \
             patch.object(fundamentacion_service, "_crear_paso", lambda *_a: fake):
            inicio = time.perf_counter()
            res = asyncio.run(fundamentacion_service.fundamentar_normativa_sync(request, None))
            duracion = time.perf_counter() - inicio

        # Mismo resultado que en serie: cada hecho con SUS artículos y en su orden.
        self.assertEqual(fake.parrafo_recibido, [(h.id, h.id) for h in hechos])
        self.assertTrue(all(h.articulos[0]["codreclamo"] == "R-9" for h in hechos))
        self.assertEqual(res["fundamentacion"], "párrafo")
        # Y en paralelo: en serie serían 0.05·(4+3+2+1) = 0.5 s.
        self.assertGreater(fake.max_concurrentes, 1)
        self.assertLess(duracion, 0.4)


class UsoTokensTest(unittest.TestCase):

    def test_lee_tokens_cacheados_del_formato_normalizado(self):
        msg = AIMessage(content="x", usage_metadata={
            "input_tokens": 1200, "output_tokens": 80, "total_tokens": 1280,
            "input_token_details": {"cache_read": 1024}})
        uso_tokens.limpiar()
        uso_tokens.desde_respuesta(msg)
        self.assertEqual(uso_tokens.ultimo(), {"entrada": 1200, "cacheados": 1024, "salida": 80})

    def test_respaldo_formato_openai(self):
        msg = AIMessage(content="x", response_metadata={"token_usage": {
            "prompt_tokens": 900, "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 0}}})
        uso_tokens.limpiar()
        uso_tokens.desde_respuesta(msg)
        self.assertEqual(uso_tokens.ultimo(), {"entrada": 900, "cacheados": 0, "salida": 50})

    def test_es_por_hilo(self):
        uso_tokens.anotar(1, 0, 1)
        visto = []
        hilo = threading.Thread(target=lambda: visto.append(uso_tokens.ultimo()))
        hilo.start(); hilo.join()
        self.assertEqual(visto, [None])


if __name__ == "__main__":
    unittest.main()
