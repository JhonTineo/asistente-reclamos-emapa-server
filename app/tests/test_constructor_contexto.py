"""Constructor de contexto: capas, especificaciones, presupuesto y registro."""

import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.src.application.services.contexto.constructor import ContextBuilder, constructor_contexto
from app.src.application.services.contexto.especificaciones import ContextSpec
from app.src.application.services.informe.informe_store import InformeAtencionStore
from app.src.application.usecase.pasos.analisis_medio import PasoAnalisisMedio
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion, ProblemaNormado
from app.src.core.model.reclamo import Reclamo
from app.src.infrastructure.adapters.persistencia.sqlite_caso_repository import SqliteCasoRepository
from app.src.infrastructure.adapters.skills.skill_file_repository import (
    DIRECTORIO_SKILLS, SkillFileRepository,
)


class RouterCaptura:
    def __init__(self, respuesta="Resumen.", error: Exception | None = None):
        self.respuesta, self.error, self.mensajes = respuesta, error, None

    def generar_texto(self, mensajes, modelo_id, temperatura=0.0, max_tokens=None):
        self.mensajes = mensajes
        if self.error:
            raise self.error
        return self.respuesta

    def generar_json(self, mensajes, modelo_id, esquema=None, temperatura=0.0, max_tokens=None):
        self.mensajes = mensajes
        return self.respuesta


class RegistroFalso:
    def __init__(self):
        self.llamadas = []

    def registrar_llamada(self, **kwargs):
        self.llamadas.append(kwargs)


def _problema(detalle, **extra):
    return ProblemaNormado(tipo="errorConsumo", detalle=detalle, **extra)


def _constatacion(detalle):
    return ProblemaNormado(tipo="lecturaMesReclamado", detalle=detalle, clase="constatacion")


def _informe(codreclamo="R-ctx") -> InformeAtencion:
    return InformeAtencion(
        numero="1", fecha=datetime(2026, 11, 13), asunto="a", reclamo=codreclamo, suministro="9",
        datos_reclamo=Reclamo(clasificacion_reclamo="A1. CONSUMO MEDIDO",
                              motivo_reclamo="Consumo elevado en setiembre",
                              meses_reclamados="SETIEMBRE-2026"),
    )


class ResumenMedioTest(unittest.TestCase):

    def setUp(self):
        self.registro = RegistroFalso()
        self.builder = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS), self.registro)

    def construir(self, **extra):
        datos = dict(medio_id="tarjeta_lectura", medio_nombre="Tarjeta de Lecturas",
                     datos={"errorConsumo": ["Consumo atípico: detectado en 09/2026"]},
                     hechos=[_problema("Consumo atípico en 09/2026", id="H-tl-01"),
                             _constatacion("En setiembre de 2026 se facturó por lectura")],
                     clasificacion="A1. CONSUMO MEDIDO")
        datos.update(extra)
        return self.builder.construir("resumen_medio", _informe(), **datos)

    def test_capas_en_orden_y_en_el_mensaje_correcto(self):
        ctx = self.construir(enfoque="¿El consumo de setiembre fue atípico?")
        self.assertEqual([c.nombre for c in ctx.capas],
                         ["rol_base", "skill", "reclamo", "hechos", "datos_medio", "tarea"])
        system, usuario = ctx.mensajes[0].contenido, ctx.mensajes[1].contenido
        # system: instrucciones + conocimiento
        self.assertTrue(system.startswith("## Rol\nEres Yumi"))
        self.assertIn("## Cómo leerlo", system)
        self.assertNotIn("Criterios de valoración", system)
        self.assertNotIn("Preguntas abiertas", system)
        self.assertNotIn("## Datos obtenidos", system)    # los datos son caso, no instrucciones
        self.assertNotIn('"errorConsumo"', system)
        # user: caso + tarea, con la tarea al final
        self.assertIn("- Meses reclamados: SETIEMBRE-2026", usuario)
        self.assertIn("- [H-tl-01] Consumo atípico en 09/2026", usuario)
        self.assertIn("HECHOS VERIFICADOS", usuario)
        self.assertIn('"errorConsumo"', usuario)
        self.assertTrue(usuario.rstrip().endswith("sin encabezados ni listas."))
        self.assertIn("¿El consumo de setiembre fue atípico?", usuario)
        self.assertEqual(
            [s.split("@")[0] for s in ctx.versiones_skills],
            ["base.reglas_generales", "medio.tarjeta_lectura"],
        )

    def test_datos_sin_campos_vacios_ni_hechos_repetidos(self):
        ctx = self.construir(
            datos={"errorConsumo": [], "descensoConsumo": [], "nomtar": "DOMESTICO",
                   "errorLecturas": ["No registro consumo y/o lectura: detectado en 03/2026",
                                     "Lectura última menor: detectado en 05/2026"]},
            hechos=[_problema("No registro consumo y/o lectura: detectado en 03/2026", id="H-tl-01")],
        )
        datos = next(c.contenido for c in ctx.capas if c.nombre == "datos_medio")
        self.assertNotIn("errorConsumo", datos)
        self.assertNotIn("descensoConsumo", datos)
        self.assertNotIn("No registro consumo", datos)          # ya va como H-tl-01
        self.assertIn("Lectura última menor", datos)
        self.assertIn('"nomtar": "DOMESTICO"', datos)

    def test_la_tarea_pide_hechos_y_no_valoraciones(self):
        tarea = self.construir(enfoque="¿Hay anomalías que justifiquen el consumo?").capas[-1].contenido
        self.assertIn("respóndela con hechos, no con una valoración", tarea)
        self.assertIn("No enumeres lo que no ocurrió", tarea)
        self.assertIn("Expresa siempre las fechas con el día y el año en cifras", self.construir().system)

    def test_recorta_solo_los_datos_del_medio(self):
        enorme = {"registros": ["x" * 200] * 400}           # ~20.000 tokens
        ctx = self.construir(datos=enorme)
        capas = {c.nombre: c for c in ctx.capas}
        self.assertTrue(capas["datos_medio"].recortada)
        self.assertIn("recortado para respetar el presupuesto", capas["datos_medio"].contenido)
        for protegida in ("rol_base", "skill", "hechos", "tarea"):
            self.assertFalse(capas[protegida].recortada)
        self.assertLessEqual(ctx.tokens_estimados, 6000)

    def test_registra_la_llamada_con_lo_que_vio_el_modelo(self):
        ctx = self.construir()
        respuesta = ctx.ejecutar_texto(RouterCaptura("Párrafo."), "openai/gpt-4o-mini")
        self.assertEqual(respuesta, "Párrafo.")
        llamada, = self.registro.llamadas
        self.assertEqual(llamada["paso"], "resumen_medio")
        self.assertEqual(llamada["codreclamo"], "R-ctx")
        self.assertEqual(llamada["modelo"], "openai/gpt-4o-mini")
        self.assertRegex(llamada["skill_version"], r"medio\.tarjeta_lectura@\d+#[0-9a-f]{12}")
        self.assertEqual(llamada["respuesta"], "Párrafo.")
        self.assertIsNone(llamada["error"])
        self.assertIn("datos_medio", llamada["capas"]["capas"])

    def test_un_error_del_llm_se_registra_y_se_propaga(self):
        ctx = self.construir()
        with self.assertRaises(RuntimeError):
            ctx.ejecutar_texto(RouterCaptura(error=RuntimeError("proveedor caído")), "m")
        self.assertIn("proveedor caído", self.registro.llamadas[0]["error"])

    def test_si_el_registro_falla_la_llamada_sigue(self):
        class RegistroRoto:
            def registrar_llamada(self, **kwargs):
                raise OSError("disco lleno")
        builder = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS), RegistroRoto())
        ctx = builder.construir("resumen_medio", _informe(), medio_id="tarjeta_lectura",
                                medio_nombre="Tarjeta", datos={}, hechos=[])
        self.assertEqual(ctx.ejecutar_texto(RouterCaptura("ok"), "m"), "ok")


class PasoAnalisisMedioConContextoTest(unittest.TestCase):

    def test_ids_de_hechos_antes_del_modelo_y_se_conservan_al_registrar(self):
        store = InformeAtencionStore()
        informe = store.crear_metadata("R-ids", "9", _informe("R-ids").datos_reclamo)
        router = RouterCaptura("Resumen de la tarjeta.")
        problemas = [_problema("Consumo atípico en 09/2026")]
        constataciones = [_constatacion("Setiembre de 2026 se facturó por lectura")]

        resumen = PasoAnalisisMedio(emapa_api=None, llm_router=router).interpretar(
            "tarjeta_lectura", "Tarjeta de Lecturas", {"errorConsumo": ["x"]}, problemas,
            "A1. CONSUMO MEDIDO", None, constataciones, informe,
        )
        usuario = router.mensajes[1].contenido
        self.assertIn("[H-tl-01] Consumo atípico", usuario)
        self.assertIn("[H-tl-02] Setiembre de 2026", usuario)
        self.assertIn("Consumo elevado en setiembre", usuario)   # datos del reclamo

        store.registrar_bloque("R-ids", BloqueMedio(
            "tarjeta_lectura", "Tarjeta de Lecturas", {}, resumen, problemas, constataciones,
        ))
        self.assertEqual([h.id for h in store.obtener("R-ids").bloques[0].hechos],
                         ["H-tl-01", "H-tl-02"])

    def test_todos_los_medios_resumen_con_su_skill(self):
        for medio in ("tarjeta_lectura", "record_facturacion", "saldo_detalle", "corte_reapertura",
                      "inspeccion_interna", "inspeccion_externa", "tecnico_operacional"):
            with self.subTest(medio=medio):
                self.assertIsNotNone(constructor_contexto.skill_de_medio(medio))
        router = RouterCaptura()
        PasoAnalisisMedio(emapa_api=None, llm_router=router).interpretar(
            "saldo_detalle", "Saldo", {"mora": ["05/2026"]},
            [_problema("Mora en 05/2026")], "A1", None, None, _informe(),
        )
        self.assertIn("# Saldo detalle", router.mensajes[0].contenido)
        self.assertIn("[H-sd-01] Mora en 05/2026", router.mensajes[1].contenido)


class ObjetivosConInformeOperacionalTest(unittest.TestCase):

    def test_el_informe_operacional_es_un_medio_valido_para_objetivos(self):
        from app.src.application.usecase.pasos.objetivos import MEDIOS, PasoObjetivos
        self.assertIn("tecnico_operacional", MEDIOS)
        objetivos = PasoObjetivos._parse(
            '[{"descripcion": "¿El sector tuvo servicio discontinuo y existe VPA operativa?", '
            '"medio": "tecnico_operacional", "determinante": true}]'
        )
        self.assertEqual(objetivos[0].medio, "tecnico_operacional")


class DictamenTest(unittest.TestCase):

    def test_reune_metodo_criterios_de_cada_medio_y_todos_los_hechos(self):
        informe = _informe()
        informe.bloques = [
            BloqueMedio("tarjeta_lectura", "Tarjeta de Lecturas", {}, "Consumo atípico.",
                        [_problema("Consumo atípico en 09/2026", id="H-tl-01",
                                   articulos=[{"article": 92, "numeral": "1", "score": 0.9,
                                               "texto": "Se considera atípica…"}])]),
            BloqueMedio("tecnico_operacional", "Informe Técnico Operacional", {},
                        "Servicio de 2:40 a 8:20.",
                        [_problema("No hay VPA en la zona", id="H-to-01")]),
        ]
        ctx = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS)).construir("dictamen", informe)
        system, usuario = ctx.mensajes[0].contenido, ctx.mensajes[1].contenido

        self.assertIn("## Método de decisión", system)
        self.assertIn("PRU-01", system)
        self.assertIn("ATI-01", system)
        self.assertIn("VPA-01", system)
        self.assertNotIn("FUG-01", system)        # inspección interna no analizada
        self.assertNotIn("## Cómo leerlo", system)
        self.assertIn("### Artículo 92, numeral 1", system)
        self.assertIn("## Hechos de Tarjeta de Lecturas", usuario)
        self.assertIn("[H-to-01] No hay VPA en la zona", usuario)
        self.assertIn("Informe Técnico Operacional: Servicio de 2:40 a 8:20.", usuario)
        self.assertIn('"veredicto_propuesto"', usuario)

    def test_no_se_pueden_recortar_capas_protegidas(self):
        with self.assertRaises(ValueError):
            ContextSpec(paso="x", capas=("hechos", "tarea"), tarea=lambda d: "",
                        recortar_primero=("hechos",))


class RegistroEnSqliteTest(unittest.TestCase):

    def test_la_llamada_queda_en_llamadas_llm_asociada_al_caso(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "yumi.db"
            repo = SqliteCasoRepository(ruta)
            try:
                store = InformeAtencionStore()
                store.configurar_persistencia(repo)
                store.crear_metadata("R-sql", "9", _informe("R-sql").datos_reclamo)
                ctx = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS), repo).construir(
                    "resumen_medio", store.obtener("R-sql"), medio_id="tarjeta_lectura",
                    medio_nombre="Tarjeta", datos={}, hechos=[],
                )
                ctx.ejecutar_texto(RouterCaptura("Hecho."), "openai/gpt-4o-mini")
                con = sqlite3.connect(ruta)
                fila = con.execute(
                    "SELECT c.codreclamo, l.paso, l.modelo, l.respuesta, l.capas "
                    "FROM llamadas_llm l JOIN casos c ON c.id = l.caso_id"
                ).fetchone()
                con.close()
            finally:
                repo.cerrar_conexion()
        self.assertEqual(fila[:4], ("R-sql", "resumen_medio", "openai/gpt-4o-mini", "Hecho."))
        self.assertIn('"tokens_aprox"', fila[4])


class ReemplazosDeProduccionTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reemplazos = Path(self.tmp.name)
        (self.reemplazos / "base").mkdir()
        self.original = (DIRECTORIO_SKILLS / "base" / "reglas_generales.md").read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_un_reemplazo_valido_se_usa_en_lugar_del_repositorio(self):
        (self.reemplazos / "base" / "reglas_generales.md").write_text(
            self.original.replace("Eres Yumi", "Eres Yumi (versión de producción)"), encoding="utf-8")
        repo = SkillFileRepository(DIRECTORIO_SKILLS, self.reemplazos)
        ctx = ContextBuilder(repo).construir("resumen_medio", None, medio_id="tarjeta_lectura",
                                             medio_nombre="T", datos={}, hechos=[])
        self.assertIn("versión de producción", ctx.system)
        self.assertEqual(repo.errores(), [])

    def test_un_reemplazo_con_errores_cae_al_repositorio(self):
        (self.reemplazos / "base" / "reglas_generales.md").write_text(
            "sin cabecera", encoding="utf-8")
        repo = SkillFileRepository(DIRECTORIO_SKILLS, self.reemplazos)
        skill, = repo.base()
        self.assertTrue(Path(skill.ruta).is_relative_to(DIRECTORIO_SKILLS))
        self.assertTrue(any("(reemplazo)" in e for e in repo.errores()))


class TodosLosPasosUsanElConstructorTest(unittest.TestCase):
    """Cada paso del workflow arma su llamada con el constructor: instrucciones
    fijas desde skills/pasos, lo del caso en el mensaje del usuario y la
    llamada queda registrada."""

    def setUp(self):
        self.registro = RegistroFalso()
        constructor_contexto.registro = self.registro

    def tearDown(self):
        constructor_contexto.registro = None

    def test_cada_especificacion_de_paso_tiene_su_skill(self):
        from app.src.application.services.contexto.especificaciones import ESPECIFICACIONES
        repo = SkillFileRepository(DIRECTORIO_SKILLS)
        for paso, spec in ESPECIFICACIONES.items():
            if spec.skill_paso:
                with self.subTest(paso=paso):
                    self.assertIsNotNone(repo.para_paso(paso))

    def test_conciliacion_separa_instrucciones_de_la_conclusion(self):
        from app.src.application.usecase.pasos.conciliacion import PasoConciliacion
        router = RouterCaptura("Propuesta.")
        PasoConciliacion(router).generar_propuesta("R-1", "infundado", "CONCLUSION DEL CASO", "77")
        system, usuario = router.mensajes[0].contenido, router.mensajes[1].contenido
        self.assertIn("PROPUESTA DE CONCILIACIÓN", system)
        self.assertIn("propone declarar INFUNDADO", system)
        self.assertIn("Eres Yumi", system)
        self.assertIn("CONCLUSION DEL CASO", usuario)
        self.assertNotIn("CONCLUSION DEL CASO", system)
        llamada, = self.registro.llamadas
        self.assertEqual((llamada["paso"], llamada["codreclamo"]), ("conciliacion", "R-1"))
        self.assertIn("paso.conciliacion@", llamada["skill_version"])

    def test_resolucion_lleva_los_datos_del_caso_en_el_usuario(self):
        from app.src.application.usecase.pasos.resolucion import CIERRE_LEGAL, PasoResolucion
        informe = _informe("R-res")
        informe.veredicto, informe.conclusion = "FUNDADO", "CONCLUSION X"
        router = RouterCaptura("QUE, ...")
        salida = PasoResolucion(router).generar_resolucion(informe, "propuesta", "aceptó")
        system, usuario = router.mensajes[0].contenido, router.mensajes[1].contenido
        self.assertIn("CONSIDERANDOS", system)
        self.assertIn("SE DECLARA FUNDADO", system)
        self.assertIn("CONCLUSION X", usuario)
        self.assertIn("13 DE NOVIEMBRE DEL 2026", usuario)
        self.assertTrue(salida["resolucion"].endswith(CIERRE_LEGAL))
        self.assertEqual(self.registro.llamadas[0]["codreclamo"], "R-res")

    def test_objetivos_y_extractor_operacional_registran_su_paso(self):
        from app.src.application.services.pre_proces.hechos_tecnico_operacional import campos_con_llm
        from app.src.application.usecase.pasos.objetivos import PasoObjetivos
        router = RouterCaptura('[{"descripcion": "¿X?", "medio": "tarjeta_lectura", "determinante": true}]')
        objetivos = PasoObjetivos(router).generar("Consumo alto", "A1", "R-obj")
        self.assertEqual(len(objetivos), 1)
        self.assertIn("PREGUNTA DECISIVA", router.mensajes[0].contenido)
        self.assertIn("- tarjeta_lectura:", router.mensajes[0].contenido)
        self.assertIn("Consumo alto", router.mensajes[1].contenido)

        router.respuesta = "{}"
        campos_con_llm("texto del informe", router, "m", "R-op")
        self.assertNotIn("Eres Yumi", router.mensajes[0].contenido)   # extractor sin rol
        self.assertIn("INFORME:\ntexto del informe", router.mensajes[1].contenido)
        self.assertEqual([ll["paso"] for ll in self.registro.llamadas],
                         ["objetivos", "extraccion_operacional"])


class RolBasePorPasoTest(unittest.TestCase):
    """El rol base acompaña solo a quien lo necesita (ver especificaciones.py)."""

    def setUp(self):
        self.builder = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS))

    def _system(self, paso):
        return self.builder.construir(paso, entrada="x").mensajes[0].contenido

    def test_los_pasos_que_solo_eligen_indices_no_llevan_rol_base(self):
        for paso in ("fundamentacion_seleccion", "fundamentacion_aplicabilidad",
                     "fundamentacion_interpretacion", "evaluacion_objetivos"):
            system = self._system(paso)
            self.assertNotIn("Eres Yumi", system, paso)
            self.assertNotIn("## Cómo escribir", system, paso)

    def test_los_pasos_que_redactan_llevan_el_rol_base_completo_y_un_solo_rol(self):
        for paso in ("fundamentacion_parrafo", "conclusion_redaccion", "conciliacion", "resolucion"):
            system = self._system(paso)
            self.assertIn("## Cómo escribir", system, paso)
            self.assertEqual(system.count("Eres "), 1, paso)     # solo «Eres Yumi»

    def test_objetivos_lleva_el_rol_sin_las_reglas_de_estilo(self):
        system = self._system("objetivos")
        self.assertIn("Eres Yumi", system)
        self.assertIn("## Reglas sobre los datos", system)
        self.assertNotIn("## Cómo escribir", system)

    def test_el_rol_base_no_trae_codigos_ni_cifras_de_ejemplo(self):
        """Un código de hecho de ejemplo terminó copiado en un informe, y las
        cifras de ejemplo eran las de un reclamo real."""
        base = self._system("fundamentacion_parrafo")
        self.assertNotRegex(base, r"\[H-[a-z]+-\d+\]")
        for dato in ("54 m³", "199.00", "12 puntos de agua", "18/09/2026", "2 de noviembre"):
            self.assertNotIn(dato, base)
        self.assertNotIn("## Notas", base)                       # las notas son para personas


class TextoSinIdentificadoresTest(unittest.TestCase):

    def test_un_texto_redactado_nunca_sale_con_codigos_de_hechos(self):
        registro = RegistroFalso()
        crudo = "El hecho [H-tl-01] de que se facturaron 54 m³ [H-rf-01] corresponde al artículo 91."
        texto = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS), registro).llamar(
            "fundamentacion_parrafo", RouterCaptura(crudo), "m", entrada="x")
        self.assertEqual(texto, "El hecho de que se facturaron 54 m³ corresponde al artículo 91.")
        self.assertEqual(registro.llamadas[0]["respuesta"], crudo)   # el registro guarda lo que llegó

    def test_un_json_conserva_los_codigos(self):
        crudo = '{"hechos": ["H-tl-01"], "nota": "[H-tl-01]"}'
        respuesta = ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS)).construir(
            "dictamen", _informe()).ejecutar_json(RouterCaptura(crudo), "m")
        self.assertEqual(respuesta, crudo)


class ModeloRealEnElRegistroTest(unittest.TestCase):

    def test_registra_el_proveedor_y_el_modelo_que_respondieron(self):
        from app.src.application.services.llm.llm_router_service import LlmRouterService

        class Catalogo:
            def modelos_para_proveedor(self, pid):
                return {"caido": ["modelo-a"], "sano": ["modelo-b"]}[pid]

        class Proveedor:
            def __init__(self, falla):
                self.falla, self.max_tokens = falla, None

            def generar_texto(self, mensajes, modelo_id, temperatura=0.0, max_tokens=None):
                if self.falla:
                    raise RuntimeError("caído")
                self.max_tokens = max_tokens
                return "Texto."

            generar_json = None

        sano = Proveedor(False)
        router = LlmRouterService(Catalogo(), {"caido": Proveedor(True), "sano": sano},
                                  ["caido", "sano"])
        registro = RegistroFalso()
        ContextBuilder(SkillFileRepository(DIRECTORIO_SKILLS), registro).llamar(
            "fundamentacion_parrafo", router, "auto", entrada="x")

        llamada = registro.llamadas[0]
        self.assertEqual((llamada["proveedor"], llamada["modelo"]), ("sano", "modelo-b"))
        self.assertIsNone(sano.max_tokens)        # sin tope propio, rige el del adaptador


if __name__ == "__main__":
    unittest.main()
