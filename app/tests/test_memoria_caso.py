"""Memoria del caso persistente: registro de hechos + repositorio SQLite."""

import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.src.application.services.informe.hechos import asignar_ids_bloque
from app.src.application.services.informe.informe_store import (
    InformeAtencionStore, ReclamoEnAtencionError, informe_store,
)
from app.src.core.model.conciliacion import Conciliacion
from app.src.core.model.informe_atencion import (
    BloqueMedio, InformeAtencion, MotivoEvaluacion, ObjetivoInvestigacion,
    ProblemaNormado,
)
from app.src.core.model.reclamo import Reclamo
from app.src.infrastructure.adapters.persistencia.sqlite_caso_repository import SqliteCasoRepository
from app.src.infrastructure.api_rest.persistencia_middleware import PersistenciaCasosMiddleware


def _problema(detalle: str, tipo: str = "errorConsumo", **extra) -> ProblemaNormado:
    return ProblemaNormado(tipo=tipo, detalle=detalle, fuente="tarjeta", **extra)


def _bloque(medio_id: str, *problemas: ProblemaNormado, resumen: str = "Resumen") -> BloqueMedio:
    return BloqueMedio(
        medio_id=medio_id, medio_nombre=medio_id.replace("_", " ").title(),
        entidad={"registros": [{"mes": "2025-12", "consumo": 48}], "total": 3},
        resumen=resumen, problemas=list(problemas),
    )


def _informe_completo(codreclamo: str = "R-1") -> InformeAtencion:
    informe = InformeAtencion(
        numero=f"{codreclamo}-2026-EMAPA-SM",
        fecha=datetime(2026, 11, 13, 10, 30),
        asunto="RESULTADOS",
        reclamo=codreclamo,
        suministro="12345",
        destinatario="Jefe",
        datos_reclamo=Reclamo(codcliente="12345", motivo_reclamo="Consumo elevado",
                              clasificacion_reclamo="Consumo medido"),
        medios_probatorios=[{"id": "tarjeta_lectura", "nombre": "Tarjeta de Lecturas"}],
        objetivos=[
            ObjetivoInvestigacion(id=1, descripcion="¿Hubo fuga?", medio="inspeccion_interna",
                                  determinante=True, resultado="sin_correccion",
                                  evidencia="sin fuga"),
            ObjetivoInvestigacion(id=2, descripcion="¿Lectura real?", medio="tarjeta_lectura"),
        ],
        ventana_meses=[(2025, 11), (2025, 12)],
        sesion_id="pestana-a",
        creado_por="analista1",
    )
    bloque = _bloque(
        "tarjeta_lectura",
        _problema("Consumo de 12/2025 = 48 m³", seleccionado=True, responsable="cliente",
                  articulos=[{"article": 88, "numeral": "2", "score": 0.91, "texto": "Art. 88"}]),
        _problema("Lectura estimada en 11/2025", tipo="observacion", texto_original="sin acceso"),
    )
    asignar_ids_bloque(informe, bloque)
    informe.bloques.append(bloque)
    informe.fundamentacion_normativa = "Según el artículo 88..."
    informe.conclusion = "En consecuencia, ... se declara INFUNDADO"
    informe.veredicto = "INFUNDADO"
    informe.estado_evaluacion = "completada"
    informe.motivos_evaluacion = [MotivoEvaluacion(codigo="X", objetivos_afectados=[1])]
    informe.origen_decision = "automatica"
    informe.propuesta_conciliacion = Conciliacion(propuesta_empresa="Mantener el cobro")
    informe.resolucion = "Se resuelve..."
    informe.historial_decisiones = [{"fecha": "2026-11-12T09:00:00", "veredicto": "FUNDADO",
                                     "estado_evaluacion": "completada",
                                     "invalidada_por": "nuevo análisis"}]
    return informe


class BaseSqlite(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "sub" / "yumi.db"
        self.repo = SqliteCasoRepository(self.ruta)

    def tearDown(self):
        self.repo.cerrar_conexion()
        self.dir.cleanup()

    def consulta(self, sql: str, *params):
        con = sqlite3.connect(self.ruta)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()


class IdsDeHechosTest(unittest.TestCase):

    def _informe(self) -> InformeAtencion:
        return InformeAtencion(numero="n", fecha=datetime.now(), asunto="a",
                               reclamo="R", suministro="s")

    def test_ids_por_medio_y_reutilizacion(self):
        informe = self._informe()
        primero = _bloque("tarjeta_lectura", _problema("A"), _problema("B"))
        asignar_ids_bloque(informe, primero)
        self.assertEqual([p.id for p in primero.problemas], ["H-tl-01", "H-tl-02"])

        # Re-análisis: B se repite (conserva su ID), C es nuevo.
        segundo = _bloque("tarjeta_lectura", _problema("B"), _problema("C"))
        asignar_ids_bloque(informe, segundo, primero)
        self.assertEqual([p.id for p in segundo.problemas], ["H-tl-02", "H-tl-03"])

    def test_no_reutiliza_ids_de_hechos_reemplazados(self):
        informe = self._informe()
        primero = _bloque("tarjeta_lectura", _problema("A"), _problema("B"))
        asignar_ids_bloque(informe, primero)
        segundo = _bloque("tarjeta_lectura", _problema("A"))
        asignar_ids_bloque(informe, segundo, primero)
        tercero = _bloque("tarjeta_lectura", _problema("A"), _problema("D"))
        asignar_ids_bloque(informe, tercero, segundo)
        # H-tl-02 (B) fue reemplazado: D no puede tomar ese número.
        self.assertEqual([p.id for p in tercero.problemas], ["H-tl-01", "H-tl-03"])

    def test_problemas_duplicados_reciben_ids_distintos(self):
        informe = self._informe()
        bloque = _bloque("inspeccion_interna", _problema("X"), _problema("X"))
        asignar_ids_bloque(informe, bloque)
        self.assertEqual([p.id for p in bloque.problemas], ["H-ii-01", "H-ii-02"])


class RepositorioSqliteTest(BaseSqlite):

    def test_ida_y_vuelta_conserva_el_informe(self):
        original = _informe_completo()
        self.repo.guardar(original)

        otro = SqliteCasoRepository(self.ruta)
        try:
            recuperados = otro.cargar_abiertos()
        finally:
            otro.cerrar_conexion()
        self.assertEqual(len(recuperados), 1)
        self.assertEqual(asdict(recuperados[0]), asdict(original))

    def test_guardar_es_idempotente_y_versiona_artefactos(self):
        informe = _informe_completo()
        self.repo.guardar(informe)
        self.repo.guardar(informe)
        self.assertEqual(
            self.consulta("SELECT COUNT(*) FROM artefactos WHERE tipo = 'conclusion'"), [(1,)],
        )

        informe.conclusion = "En consecuencia, ... se declara FUNDADO"
        self.repo.guardar(informe)
        self.assertEqual(
            self.consulta("SELECT version, vigente FROM artefactos "
                          "WHERE tipo = 'conclusion' ORDER BY version"),
            [(1, 0), (2, 1)],
        )

        # Un artefacto que desaparece deja de estar vigente, sin borrarse.
        informe.conclusion = None
        self.repo.guardar(informe)
        self.assertEqual(
            self.consulta("SELECT COUNT(*), SUM(vigente) FROM artefactos WHERE tipo = 'conclusion'"),
            [(2, 0)],
        )

    def test_hecho_que_desaparece_queda_reemplazado(self):
        informe = _informe_completo()
        self.repo.guardar(informe)
        anterior = informe.bloques[0]
        nuevo = _bloque("tarjeta_lectura", _problema("Consumo de 12/2025 = 48 m³"))
        asignar_ids_bloque(informe, nuevo, anterior)
        informe.bloques = [nuevo]
        self.repo.guardar(informe)

        self.assertEqual(
            self.consulta("SELECT id, estado FROM hechos ORDER BY id"),
            [("H-tl-01", "vigente"), ("H-tl-02", "reemplazado")],
        )
        recuperado = self.repo.cargar_abiertos()[0]
        self.assertEqual([p.id for p in recuperado.bloques[0].problemas], ["H-tl-01"])

    def test_historial_de_decisiones_solo_agrega_entradas_nuevas(self):
        informe = _informe_completo()
        self.repo.guardar(informe)
        self.repo.guardar(informe)
        informe.historial_decisiones.append({"veredicto": "INFUNDADO", "estado_evaluacion": "completada"})
        self.repo.guardar(informe)
        self.assertEqual(
            self.consulta("SELECT COUNT(*) FROM decisiones WHERE vigente = 0"), [(2,)],
        )
        self.assertEqual(
            self.consulta("SELECT veredicto FROM decisiones WHERE vigente = 1"), [("INFUNDADO",)],
        )


class StorePersistenteTest(BaseSqlite):

    def setUp(self):
        super().setUp()
        self.store = InformeAtencionStore()
        self.store.configurar_persistencia(self.repo)

    def test_edicion_del_analista_y_regeneracion(self):
        informe = self.store.crear_metadata("R-2", "999", Reclamo(motivo_reclamo="m"))
        informe.conclusion = "Texto generado"
        self.store.persistir_cambios()
        self.store.actualizar_conclusion("R-2", "Texto corregido por el analista")
        informe.conclusion = "Texto regenerado"
        self.store.persistir_cambios()

        self.assertEqual(
            self.consulta("SELECT version, origen, vigente FROM artefactos "
                          "WHERE tipo = 'conclusion' ORDER BY version"),
            [(1, "generado", 0), (2, "analista", 0), (3, "generado", 1)],
        )

    def test_registrar_bloque_asigna_ids_y_persiste(self):
        self.store.crear_metadata("R-3", "999")
        self.store.registrar_bloque("R-3", _bloque("saldo_detalle", _problema("Mora")))
        self.assertEqual(self.consulta("SELECT id FROM hechos"), [("H-sd-01",)])

    def test_recupera_atenciones_y_respeta_el_bloqueo_de_sesion(self):
        self.store.crear_metadata("R-4", "999", sesion_id="pestana-a")

        reiniciado = InformeAtencionStore()
        self.assertEqual(reiniciado.configurar_persistencia(self.repo), 1)
        with self.assertRaises(ReclamoEnAtencionError):
            reiniciado.crear_metadata("R-4", "999", sesion_id="pestana-b")

    def test_finalizar_conserva_y_descartar_borra(self):
        self.store.crear_metadata("R-5", "999")
        self.store.eliminar("R-5")
        self.assertEqual(self.consulta("SELECT estado FROM casos"), [("finalizado",)])

        # Una nueva atención del mismo reclamo es posible tras finalizar.
        self.store.crear_metadata("R-5", "999")
        self.store.eliminar("R-5", descartar=True)
        self.assertEqual(self.consulta("SELECT estado FROM casos"), [("finalizado",)])
        self.assertEqual(InformeAtencionStore().configurar_persistencia(self.repo), 0)


class MiddlewarePersistenciaTest(BaseSqlite):

    def setUp(self):
        super().setUp()
        informe_store.configurar_persistencia(self.repo)
        app = FastAPI()
        app.add_middleware(PersistenciaCasosMiddleware)

        @app.post("/mutar")
        def mutar():
            # Simula a un agente que modifica el informe sin pasar por el store.
            informe_store.obtener("R-mw").conclusion = "Conclusión directa"
            return {"ok": True}

        @app.post("/stream")
        def stream():
            def generador():
                yield "a\n"
                informe_store.obtener("R-mw").fundamentacion_normativa = "Durante el stream"
                yield "b\n"
            return StreamingResponse(generador(), media_type="application/x-ndjson")

        self.client = TestClient(app)
        informe_store.crear_metadata("R-mw", "999")

    def tearDown(self):
        informe_store.eliminar("R-mw", descartar=True)
        informe_store.configurar_persistencia(None)
        super().tearDown()

    def test_guarda_cambios_directos_al_terminar_la_peticion(self):
        self.client.post("/mutar")
        self.assertEqual(
            self.consulta("SELECT texto FROM artefactos WHERE tipo = 'conclusion'"),
            [("Conclusión directa",)],
        )

    def test_guarda_cambios_hechos_durante_un_stream(self):
        respuesta = self.client.post("/stream")
        self.assertEqual(respuesta.text, "a\nb\n")
        self.assertEqual(
            self.consulta("SELECT texto FROM artefactos WHERE tipo = 'fundamentacion'"),
            [("Durante el stream",)],
        )


if __name__ == "__main__":
    unittest.main()
