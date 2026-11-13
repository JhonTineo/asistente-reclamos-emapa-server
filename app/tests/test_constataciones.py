"""Constataciones (hechos neutros o favorables) con los datos del reclamo 252357.

Ese caso produjo un informe con dos contradicciones: la tarjeta decía que "no
hay información" de setiembre (el LLM no recibía los registros mensuales) y la
fundamentación quedó vacía porque los medios determinantes no tenían problemas.
Solo se usan datos de consumo, facturación e inspecciones (nada personal).
"""

import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.src.application.services.informe.hechos import asignar_ids_bloque
from app.src.application.services.pre_proces.constataciones import extraer_constataciones
from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.usecase.agents.conclusion import ConclusionAgent
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.core.model.informe_atencion import (
    BloqueMedio, InformeAtencion, ObjetivoInvestigacion, ProblemaNormado,
)
from app.src.core.model.reclamo import Reclamo
from app.src.infrastructure.adapters.persistencia.sqlite_caso_repository import (
    MIGRACIONES, SqliteCasoRepository,
)

SETIEMBRE = [(2026, 9)]

# (anio, mes, lectura anterior, lectura última, consumo, promedio, estado, fecha)
_LECTURAS = [
    (2025, 11, 53, 138, 85, 68, "LECTURA NORMAL", "2025-11-15"),
    (2025, 12, 138, 240, 102, 61, "LECTURA NORMAL", "2025-12-17"),
    (2026, 1, 240, 309, 69, 69, "LECTURA NORMAL", "2026-01-17"),
    (2026, 2, 309, 394, 85, 94, "LECTURA NORMAL", "2026-02-16"),
    (2026, 3, 394, 473, 79, 75, "LECTURA NORMAL", "2026-03-18"),
    (2026, 4, 473, 501, 28, 78, "CONSUMO MENOR AL PROMEDIO", "2026-04-17"),
    (2026, 5, 501, 653, 152, 74, "CONSUMO EXCESIVO", "2026-05-18"),
    (2026, 6, 653, 741, 88, 85, "LECTURA NORMAL", "2026-06-17"),
    (2026, 7, 741, 851, 110, 75, "LECTURA NORMAL", "2026-07-18"),
    (2026, 8, 851, 982, 131, 76, "LECTURA NORMAL", "2026-08-17"),
    (2026, 9, 982, 1133, 151, 86, "LECTURA NORMAL", "2026-09-16"),
    (2026, 10, 1133, 1261, 128, 97, "LECTURA NORMAL", "2026-10-17"),
]

TARJETA = {
    "nro_medidor": "TA25074098",
    "fecha_instalacion_medidor": "2025-09-25 00:00:00.0",
    "errorConsumo": ["Consumo excesivo: detectado en 05/2026"],
    "registros": [
        {"anio": a, "mes": m, "lecturaanterior": float(la), "lecturaultima": float(lu),
         "consumo": float(c), "lecturapromedio": float(p), "desestadolectura": e,
         "desestadomed": "BUENA CONDICION", "fechalecturault": f}
        for a, m, la, lu, c, p, e, f in _LECTURAS
    ],
}

# (anio, mes, consumo, importe, rebaja, fecha rebaja)
_FACTURAS = [
    (2026, 2, 85, 570.2, 17.5, "2026-02-28 23:28:51.84"),
    (2026, 5, 152, 1128.2, 533.1, "2026-07-20 16:57:52.373"),
    (2026, 8, 131, 953.3, None, None),
    (2026, 9, 151, 1119.9, None, None),
]

RECORD = {
    "categoria": "COMERCIAL",
    "registros": [
        {"anio": a, "mes": m, "tipopromedio": "0", "tipopromedio_texto": "MEDIDO",
         "consumo": float(c), "consumofac": float(c), "impmestotal": imp,
         "c_impmesrebaja": reb, "c_diarebaja": freb}
        for a, m, c, imp, reb, freb in _FACTURAS
    ],
}

INSP_EXTERNA = {
    "nroinspeccion": 11729, "fechainspeccion": "2026-10-19",
    "funcionamed": "El medidor funciona correctamente.",
    "fugas": "No se detectaron fugas de agua.", "tipofugas": "No Hay",
    "observacionmed": "BUEN ESTADO\n",
    "estadocaja": "La caja del medidor está en buen estado.",
    "estconexion": "La conexión del medidor está en buen estado.",
}

OBS_INTERNA = ("PREDIO DE 1 PISO, FACHADA COLOR BLANCO CON PORTON VERDE, SE LLAMO A "
               "USUARIO Y NO HUBO RESPUESTA, SE REALIZO INSPECCION EXTERNA")
INSP_INTERNA = {
    "nroinspeccion": 11722, "fechainspeccion": "2026-10-19",
    "atipico": "No hubo consumos atípicos en la inspección.",
    "obsinsinteriores": OBS_INTERNA, "observaciones": "", "obsperrepins": "",
    "puntos_agua": [],
}

CORTE = {
    "totalProrrogas": 4,
    "prorrogas": ["2026-05: prórroga", "2026-08: prórroga", "2026-09: prórroga, prórroga"],
}


def _por_tipo(hechos: list[ProblemaNormado]) -> dict[str, ProblemaNormado]:
    return {h.tipo: h for h in hechos}


class ReglasDeConstatacionTest(unittest.TestCase):

    def test_tarjeta_siempre_verifica_el_mes_reclamado(self):
        hechos = _por_tipo(extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE))
        lectura = hechos["lecturaMesReclamado"]
        for parte in ("setiembre de 2026", "982 a 1133", "16/09/2026", "151 m³",
                      "promedio de 86 m³", "1.8 veces", "la lectura figura como lectura normal",
                      "medidor en buena condicion"):
            self.assertIn(parte, lectura.detalle)
        self.assertEqual(lectura.periodo, "2026-09")
        self.assertEqual(lectura.valor["consumo_m3"], 151.0)
        self.assertEqual(lectura.clase, "constatacion")

    def test_tarjeta_detecta_tendencia_y_medidor_reciente(self):
        hechos = _por_tipo(extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE))
        self.assertIn("junio de 2026 hasta setiembre de 2026 (88, 110, 131 y 151 m³)",
                      hechos["tendenciaCreciente"].detalle)
        self.assertIn("instalado el 25/09/2025, 12 meses antes", hechos["medidorReciente"].detalle)

    def test_mes_sin_lectura_se_constata_en_vez_de_inventarse(self):
        hechos = extraer_constataciones("tarjeta_lectura", TARJETA, [(2027, 1)])
        self.assertEqual([h.tipo for h in hechos], ["sinLecturaMesReclamado"])
        self.assertIn("enero de 2027", hechos[0].detalle)

    def test_record_facturacion_y_rebajas(self):
        hechos = extraer_constataciones("record_facturacion", RECORD, SETIEMBRE)
        factura = _por_tipo(hechos)["facturacionMesReclamado"]
        self.assertEqual(
            factura.detalle,
            "En setiembre de 2026 se facturó por la lectura del medidor, con un "
            "consumo de 151 m³ y un importe de S/ 1,119.90.",
        )
        rebajas = [h.detalle for h in hechos if h.tipo == "rebajaAplicada"]
        self.assertEqual(len(rebajas), 2)
        self.assertIn("mayo de 2026 se le aplicó una rebaja de S/ 533.10, registrada el 20/07/2026",
                      rebajas[1])

    def test_inspeccion_externa(self):
        hechos = _por_tipo(extraer_constataciones("inspeccion_externa", INSP_EXTERNA))
        self.assertEqual(
            hechos["estadoMedidorInspeccion"].detalle,
            "En la inspección externa del 19/10/2026, el medidor funciona correctamente "
            "(observación del inspector, buen estado).",
        )
        self.assertEqual(
            hechos["fugasInspeccionExterna"].detalle,
            "En la inspección externa del 19/10/2026, no se detectaron fugas de agua.",
        )

    def test_inspeccion_interna_sin_acceso(self):
        hechos = extraer_constataciones("inspeccion_interna", INSP_INTERNA)
        self.assertEqual(len(hechos), 1)
        self.assertEqual(hechos[0].tipo, "inspeccionInternaSinAcceso")
        self.assertEqual(
            hechos[0].detalle,
            "El 19/10/2026 no se pudo inspeccionar el interior del predio porque no "
            "hubo respuesta del usuario.",
        )
        self.assertEqual(hechos[0].texto_original, OBS_INTERNA)

    def test_inspeccion_interna_ambigua_no_afirma_nada(self):
        datos = {**INSP_INTERNA, "obsinsinteriores": "PREDIO DE 1 PISO"}
        self.assertEqual(extraer_constataciones("inspeccion_interna", datos), [])

    def test_prorrogas_de_corte(self):
        hechos = extraer_constataciones("corte_reapertura", CORTE)
        self.assertEqual(
            hechos[0].detalle,
            "Se registraron 4 prórrogas de corte del servicio (05/2026, 08/2026, 09/2026).",
        )

    def test_ninguna_constatacion_usa_dos_puntos(self):
        # La búsqueda normativa toma lo que va antes de ":" como concepto.
        todos = [
            *extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE),
            *extraer_constataciones("record_facturacion", RECORD, SETIEMBRE),
            *extraer_constataciones("inspeccion_externa", INSP_EXTERNA),
            *extraer_constataciones("inspeccion_interna", INSP_INTERNA),
            *extraer_constataciones("corte_reapertura", CORTE),
        ]
        self.assertTrue(todos)
        for hecho in todos:
            self.assertNotIn(":", hecho.detalle, hecho.detalle)

    def test_datos_vacios_solo_constatan_la_ausencia_del_mes(self):
        tipos = {
            medio: [h.tipo for h in extraer_constataciones(medio, {}, SETIEMBRE)]
            for medio in ("tarjeta_lectura", "record_facturacion", "inspeccion_externa",
                          "inspeccion_interna", "corte_reapertura", "saldo_detalle")
        }
        self.assertEqual(tipos, {
            "tarjeta_lectura": ["sinLecturaMesReclamado"],
            "record_facturacion": ["sinFacturacionMesReclamado"],
            "inspeccion_externa": [], "inspeccion_interna": [],
            "corte_reapertura": [], "saldo_detalle": [],
        })


class RouterCaptura:
    def __init__(self, respuesta: str = "Resumen."):
        self.respuesta = respuesta
        self.mensajes = None

    def generar_texto(self, mensajes, modelo_id, temperatura=0.0):
        self.mensajes = mensajes
        return self.respuesta

    def generar_json(self, mensajes, modelo_id, esquema=None, temperatura=0.0):
        self.mensajes = mensajes
        return self.respuesta


class UsoDeLasConstatacionesTest(unittest.TestCase):

    def test_el_resumen_recibe_el_mes_reclamado_como_hecho_verificado(self):
        router = RouterCaptura()
        agente = AnalistaMedioAgent(emapa_api=None, llm_router=router)
        constataciones = extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE)
        problemas = [ProblemaNormado(tipo="errorConsumo", detalle="Consumo excesivo: detectado en 05/2026")]
        agente.interpretar("tarjeta_lectura", "Tarjeta de Lecturas", TARJETA, problemas,
                           "A1. CONSUMO MEDIDO", None, constataciones)
        humano = router.mensajes[1].contenido
        self.assertIn("HECHOS VERIFICADOS", humano)
        self.assertIn("982 a 1133", humano)
        self.assertIn("No afirmes que falta información", humano)

    def test_frase_fija_se_completa_con_los_hechos(self):
        agente = AnalistaMedioAgent(emapa_api=None, llm_router=None)  # no debe usar el LLM
        constataciones = extraer_constataciones("corte_reapertura", CORTE)
        texto = agente.interpretar("corte_reapertura", "Cortes y Reaperturas", CORTE, [],
                                   "A1. CONSUMO MEDIDO", None, constataciones)
        self.assertEqual(
            texto,
            "Revisados los cortes y reaperturas del cliente no se encontraron problemas. "
            "Se registraron 4 prórrogas de corte del servicio (05/2026, 08/2026, 09/2026).",
        )

    def _informe(self) -> InformeAtencion:
        informe = InformeAtencion(
            numero="1", fecha=datetime(2026, 11, 13), asunto="a", reclamo="252357",
            suministro="s", datos_reclamo=Reclamo(meses_reclamados="SETIEMBRE-2026",
                                                  motivo_reclamo="Consumo elevado"),
            objetivos=[
                ObjetivoInvestigacion(id=2, descripcion="¿Hubo fuga interna?",
                                      medio="inspeccion_interna", determinante=True),
                ObjetivoInvestigacion(id=3, descripcion="¿Se facturó por lectura real?",
                                      medio="record_facturacion", determinante=True),
            ],
        )
        for medio, datos in (("inspeccion_interna", INSP_INTERNA),
                             ("inspeccion_externa", INSP_EXTERNA),
                             ("record_facturacion", RECORD)):
            bloque = BloqueMedio(medio_id=medio, medio_nombre=medio, entidad=datos,
                                 resumen="Resumen.",
                                 constataciones=extraer_constataciones(medio, datos, SETIEMBRE))
            asignar_ids_bloque(informe, bloque)
            informe.bloques.append(bloque)
        return informe

    def test_el_evaluador_ve_los_hechos_verificados(self):
        hallazgos = ConclusionAgent._hallazgos_por_medio(self._informe())
        self.assertIn("Hecho verificado: En setiembre de 2026 se facturó por la lectura del medidor",
                      hallazgos["record_facturacion"])
        self.assertIn("no hubo respuesta del usuario", hallazgos["inspeccion_interna"])

    def test_la_fundamentacion_puede_elegir_hechos_verificados(self):
        # Antes: medios determinantes sin problemas -> fundamentación vacía.
        informe = self._informe()
        # Pool: [0] interna sin acceso, [1-3] externa (complementa a la interna
        # en el mismo objetivo), [4] facturación de setiembre, [5-6] rebajas.
        router = RouterCaptura("[0, 1, 4]")
        agente = FundamentacionNormativaAgent.__new__(FundamentacionNormativaAgent)
        agente.llm_router, agente.model_id = router, "falso"
        elegidos = agente.seleccionar_determinantes(informe)
        self.assertEqual([h.tipo for h in elegidos],
                         ["inspeccionInternaSinAcceso", "estadoMedidorInspeccion",
                          "facturacionMesReclamado"])
        self.assertTrue(all(h.seleccionado for h in elegidos))
        self.assertIn("(hecho verificado)", router.mensajes[1].contenido)


class AlcanceYLimitacionesTest(unittest.TestCase):
    """Correcciones A-D tras la segunda corrida del reclamo 252357, cuya
    conclusión afirmó que no hubo fugas «en las instalaciones» aunque el
    interior nunca se inspeccionó."""

    def _informe(self) -> InformeAtencion:
        informe = UsoDeLasConstatacionesTest._informe(self)
        # La tarjeta NO es medio determinante en este caso (objetivo 1 de contexto).
        tarjeta = BloqueMedio(
            medio_id="tarjeta_lectura", medio_nombre="Tarjeta de Lecturas", entidad=TARJETA,
            resumen="Resumen.",
            constataciones=extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE),
        )
        asignar_ids_bloque(informe, tarjeta)
        informe.bloques.append(tarjeta)
        return informe

    def _fundamentador(self, respuesta: str):
        agente = FundamentacionNormativaAgent.__new__(FundamentacionNormativaAgent)
        agente.llm_router, agente.model_id = RouterCaptura(respuesta), "falso"
        return agente

    # --- C: días entre lecturas ------------------------------------------
    def test_lectura_del_mes_incluye_los_dias_entre_lecturas(self):
        lectura = _por_tipo(extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE))[
            "lecturaMesReclamado"]
        self.assertIn("Entre la lectura anterior (17/08/2026) y esta transcurrieron 30 días, "
                      "dentro del periodo de 28 a 32 días", lectura.detalle)
        self.assertEqual(lectura.valor["dias_entre_lecturas"], 30)

    def test_periodo_de_lectura_fuera_de_rango(self):
        datos = {"registros": [
            {"anio": 2026, "mes": 8, "consumo": 10.0, "fechalecturault": "2026-08-01"},
            {"anio": 2026, "mes": 9, "consumo": 20.0, "fechalecturault": "2026-09-10"},
        ]}
        lectura = extraer_constataciones("tarjeta_lectura", datos, SETIEMBRE)[0]
        self.assertIn("transcurrieron 40 días, fuera del periodo de 28 a 32 días", lectura.detalle)

    # --- A: limitaciones obligatorias + hechos del mes reclamado ----------
    def test_la_limitacion_se_selecciona_aunque_el_llm_la_omita(self):
        agente = self._fundamentador("[1, 4]")   # medidor + facturación, SIN la interna
        elegidos = agente.seleccionar_determinantes(self._informe())
        self.assertIn("inspeccionInternaSinAcceso", [h.tipo for h in elegidos])

    def test_la_lectura_del_mes_es_candidata_aunque_su_medio_no_sea_determinante(self):
        informe = self._informe()
        candidatos = FundamentacionNormativaAgent.candidatos(informe)
        tipos_tarjeta = [h.tipo for medio, h in candidatos if medio == "tarjeta_lectura"]
        # Solo los hechos del mes reclamado, no la tendencia ni el medidor.
        self.assertEqual(tipos_tarjeta, ["lecturaMesReclamado"])

        agente = self._fundamentador("[]")
        agente.seleccionar_determinantes(informe)
        humano = agente.llm_router.mensajes[1].contenido
        self.assertIn("Hechos del mes reclamado (de otros medios)", humano)
        self.assertIn("transcurrieron 30 días", humano)

    # --- B: alcance en la fundamentación ------------------------------------
    def test_la_fundamentacion_conserva_el_alcance(self):
        agente = self._fundamentador("Párrafo.")
        hechos = extraer_constataciones("inspeccion_externa", INSP_EXTERNA)
        agente.redactar_parrafo(hechos, "Consumo elevado", "A1. CONSUMO MEDIDO")
        sistema = agente.llm_router.mensajes[0].contenido
        self.assertIn("CONSERVA EL ALCANCE", sistema)
        self.assertIn("no acredita el estado de las instalaciones INTERNAS", sistema)
        self.assertIn("Cita SOLO el inciso", sistema)

    # --- D: la conclusión recibe los hechos y nombra la limitación ----------
    def test_la_conclusion_recibe_hechos_y_nombra_la_limitacion(self):
        informe = self._informe()
        informe.fundamentacion_normativa = "Conforme al artículo 91 inciso f)..."
        determinantes = [o for o in informe.objetivos if o.determinante]
        determinantes[0].resultado = "no_evaluable"
        determinantes[1].resultado = "sin_correccion"
        router = RouterCaptura("En consecuencia, ... se declara INFUNDADO.")
        agente = ConclusionAgent(llm_router=router, criterios=[])
        agente._redactar_conclusion(informe, "INFUNDADO", determinantes, [])

        sistema, humano = router.mensajes[0].contenido, router.mensajes[1].contenido
        self.assertIn("no hubo respuesta del usuario", humano)
        self.assertIn("transcurrieron 30 días", humano)          # hecho del mes reclamado
        self.assertIn("Hay una LIMITACIÓN de la verificación", sistema)
        self.assertIn("nunca escribas que no hubo fugas o problemas «en las instalaciones»", sistema)
        self.assertIn("NO repitas su contenido", sistema)
        self.assertIn("no la sustituyas por una fórmula genérica", sistema)


class PersistenciaDeConstatacionesTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ruta = Path(self.dir.name) / "yumi.db"

    def tearDown(self):
        self.dir.cleanup()

    def test_ids_compartidos_e_ida_y_vuelta(self):
        informe = InformeAtencion(numero="n", fecha=datetime(2026, 11, 13), asunto="a",
                                  reclamo="R", suministro="s")
        bloque = BloqueMedio(
            medio_id="tarjeta_lectura", medio_nombre="Tarjeta", entidad=TARJETA, resumen="r",
            problemas=[ProblemaNormado(tipo="errorConsumo", detalle="Consumo excesivo: detectado en 05/2026")],
            constataciones=extraer_constataciones("tarjeta_lectura", TARJETA, SETIEMBRE),
        )
        asignar_ids_bloque(informe, bloque)
        informe.bloques.append(bloque)
        self.assertEqual([h.id for h in bloque.hechos],
                         ["H-tl-01", "H-tl-02", "H-tl-03", "H-tl-04"])

        repo = SqliteCasoRepository(self.ruta)
        repo.guardar(informe)
        recuperado = repo.cargar_abiertos()[0].bloques[0]
        repo.cerrar_conexion()
        self.assertEqual(recuperado.problemas, bloque.problemas)
        self.assertEqual(recuperado.constataciones, bloque.constataciones)

    def test_migra_una_base_de_la_version_1(self):
        con = sqlite3.connect(self.ruta)
        con.executescript(MIGRACIONES[0] + "\nPRAGMA user_version = 1;")
        con.execute("INSERT INTO casos (codreclamo, suministro) VALUES ('R', 's')")
        con.execute("INSERT INTO hechos (caso_id, id, medio_id, tipo, enunciado, origen, confianza) "
                    "VALUES (1, 'H-tl-01', 'tarjeta_lectura', 'errorConsumo', 'x', 'regla', 'dato')")
        con.commit()
        con.close()

        repo = SqliteCasoRepository(self.ruta)
        repo.cerrar_conexion()
        con = sqlite3.connect(self.ruta)
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], len(MIGRACIONES))
            self.assertEqual(con.execute("SELECT clase FROM hechos").fetchall(), [("problema",)])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
