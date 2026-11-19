"""Paso 4 (hechos para los criterios) y paso 5 (dictamen + verificador)."""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.src.application.services.informe.hechos_caso import hechos_del_caso
from app.src.application.services.informe.informe_store import InformeAtencionStore
from app.src.application.services.pre_proces.constataciones import extraer_constataciones
from app.src.application.services.pre_proces.hechos_tecnico_operacional import (
    campos_desde_formulario, extraer_hechos,
)
from app.src.application.usecase.pasos.conclusion import PasoConclusion
from app.src.application.usecase.pasos.dictamen import (
    APLICA, Factor, PasoDictamen, resolver, verificar,
)
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion, ProblemaNormado
from app.src.core.model.reclamo import Reclamo
from app.src.core.model.skill import Criterio
from app.src.infrastructure.adapters.persistencia.sqlite_caso_repository import SqliteCasoRepository

MOTIVO_252396 = (
    "NO ESTOY CONFORME CON LO FACTURADO EL MES DE SETIEMBRE YA QUE EN CASA VIVO SOLO Y "
    "SOLO REGRESO POR LAS NOCHES A REALIZAR MIS QUE HACERES Y NO CUENTO CON EL SERVICIO "
    "DE 24 HORAS COMO DICE MI RECIBO A VECES ME QUEDO DOS DÍAS SIN AGUA"
)


class RouterGuion:
    """Devuelve las respuestas JSON en orden; registra lo que recibió."""
    def __init__(self, *respuestas_json, texto="En consecuencia, … por lo tanto se declara FUNDADO."):
        self.respuestas = list(respuestas_json)
        self.texto = texto
        self.mensajes_json = []

    def generar_json(self, mensajes, modelo_id, esquema=None, temperatura=0.0, max_tokens=None):
        self.mensajes_json.append(mensajes)
        self.max_tokens = max_tokens
        respuesta = self.respuestas.pop(0)
        return respuesta if isinstance(respuesta, str) else json.dumps(respuesta, ensure_ascii=False)

    def generar_texto(self, mensajes, modelo_id, temperatura=0.0, max_tokens=None):
        return self.texto


def _caso_252396(codreclamo="252396") -> InformeAtencion:
    informe = InformeAtencion(
        numero="1", fecha=datetime(2026, 11, 13), asunto="a", reclamo=codreclamo, suministro="24578",
        datos_reclamo=Reclamo(clasificacion_reclamo="A1. CONSUMO MEDIDO",
                              motivo_reclamo=MOTIVO_252396, meses_reclamados="SETIEMBRE-2026"),
    )
    informe.bloques = [
        BloqueMedio("tarjeta_lectura", "Tarjeta de Lecturas", {}, "Lectura normal.", [], [
            ProblemaNormado(tipo="lecturaMesReclamado", clase="constatacion", id="H-tl-03",
                            detalle="En setiembre de 2026 … 15 m³ frente a un promedio de 12 m³ …"),
        ]),
        BloqueMedio("inspeccion_externa", "Inspección Externa", {}, "Sin fugas.", [], [
            ProblemaNormado(tipo="fugasInspeccionExterna", clase="constatacion", id="H-ie-02",
                            detalle="En la inspección externa del 19/10/2026, no se detectaron fugas de agua."),
        ]),
    ]
    return informe


def _respuesta_fundado() -> dict:
    return {
        "factores": [
            {"criterio": "PRU-01", "aplica": "aplica", "hechos": ["H-caso-01", "H-caso-02"],
             "favorece": "usuario",
             "explicacion": "El usuario alega discontinuidad y falta el informe operacional."},
            {"criterio": "LEC-02", "aplica": "no_aplica", "hechos": ["H-tl-03"],
             "explicacion": "La lectura es válida (30 días)."},
            {"criterio": "ATI-01", "aplica": "no_aplica", "hechos": ["H-tl-03"]},
        ],
        "conflictos": [], "pruebas_faltantes": ["informe técnico operacional"],
        "veredicto_propuesto": "FUNDADO", "razonamiento": "La empresa no acreditó …",
    }


# ---------------------------------------------------------------------- #
# Paso 4
# ---------------------------------------------------------------------- #
class HechosTecnicoOperacionalTest(unittest.TestCase):

    FORMULARIO = (
        "INFORME TECNICO OPERACIONAL … "
        "En el periodo reclamado hubo interrupciones en el abastecimiento: NO. "
        "Existencia de VPA en la zona: No hay VPA. "
        "Estado de la VPA: No determinada (sin marca X legible o marcas múltiples). "
    )

    def test_casillas_del_formulario(self):
        campos = campos_desde_formulario(self.FORMULARIO)
        self.assertIs(campos["interrupciones"]["valor"], False)
        self.assertIs(campos["vpa_existe"]["valor"], False)
        self.assertIsNone(campos["vpa_operativa"]["valor"])

    def test_extractor_narrativo_exige_cita_literal(self):
        texto = ("Se realizó el análisis de la zona. El abastecimiento es de 2:40 a 8:20 y de "
                 "17:30 a 21:50. Se confirma que no hay válvula de aire en la zona.")
        router = RouterGuion({
            "horario": {"valor": "2:40 a 8:20 y 17:30 a 21:50", "continuo": False,
                        "cita": "El abastecimiento es de 2:40 a 8:20 y de 17:30 a 21:50."},
            "interrupciones": {"valor": False, "cita": "No hubo cortes en setiembre."},  # no está
            "vpa_existe": {"valor": False, "cita": "Se confirma que no hay válvula de aire en la zona."},
            "vpa_operativa": {"valor": None, "cita": None},
        })
        hechos = {h.tipo: h for h in extraer_hechos(
            {"texto_extraido": texto, "formato": "narrativo"}, router, "m")}
        self.assertIs(hechos["horarioAbastecimiento"].valor["continuo"], False)
        self.assertIn("servicio discontinuo", hechos["horarioAbastecimiento"].detalle)
        self.assertIsNone(hechos["interrupcionesPeriodo"].valor["hubo"])   # cita inventada → descartada
        self.assertIs(hechos["vpaZona"].valor["existe"], False)
        self.assertIn("no existe válvula de purga de aire", hechos["vpaZona"].detalle)
        self.assertTrue(all(h.clase == "constatacion" for h in hechos.values()))

    def test_sin_llm_el_formulario_igual_produce_hechos(self):
        hechos = {h.tipo: h for h in extraer_hechos(
            {"texto_extraido": self.FORMULARIO, "formato": "formulario"})}
        self.assertIs(hechos["vpaZona"].valor["existe"], False)
        self.assertIs(hechos["interrupcionesPeriodo"].valor["hubo"], False)
        self.assertIsNone(hechos["horarioAbastecimiento"].valor["continuo"])


class HechosDelCasoTest(unittest.TestCase):

    def test_252396_alegacion_y_prueba_faltante(self):
        hechos = hechos_del_caso(_caso_252396())
        self.assertEqual([h.id for h in hechos], ["H-caso-01", "H-caso-02"])
        alegacion, faltante = hechos
        self.assertEqual(alegacion.clase, "alegacion")
        self.assertIn("24 HORAS", alegacion.detalle)
        self.assertEqual(faltante.tipo, "pruebaFaltante")
        self.assertEqual(faltante.valor["medio"], "tecnico_operacional")

    def test_sin_alegacion_no_se_exige_el_informe_operacional(self):
        informe = _caso_252396()
        informe.datos_reclamo.motivo_reclamo = "El consumo de setiembre es muy alto."
        self.assertEqual(hechos_del_caso(informe), [])

    def test_otro_tipo_de_reclamo_no_exige_pruebas_de_consumo_medido(self):
        informe = _caso_252396()
        informe.datos_reclamo.clasificacion_reclamo = "B1. TARIFA"
        self.assertEqual([h.tipo for h in hechos_del_caso(informe)], ["alegacionDiscontinuidad"])


class AtipicoEnLaTarjetaTest(unittest.TestCase):

    def test_meses_atipicos_consecutivos_y_episodio_previo(self):
        def fila(mes, consumo, codigo="000"):
            return {"anio": 2026, "mes": mes, "consumo": consumo, "lecturapromedio": 10,
                    "estadolectura": codigo, "lecturaanterior": 0, "lecturaultima": consumo,
                    "fechalecturault": f"2026-{mes:02d}-18"}
        registros = [fila(1, 30, "008"), fila(2, 10), fila(3, 10), fila(4, 25), fila(5, 26, "008")]
        lectura, = [h for h in extraer_constataciones("tarjeta_lectura", {"registros": registros}, [(2026, 5)])
                    if h.tipo == "lecturaMesReclamado"]
        self.assertTrue(lectura.valor["atipico"])
        self.assertEqual(lectura.valor["meses_atipicos_consecutivos"], 2)
        self.assertTrue(lectura.valor["episodio_atipico_previo_12m"])
        self.assertIn("Es un consumo atípico", lectura.detalle)


# ---------------------------------------------------------------------- #
# Paso 5
# ---------------------------------------------------------------------- #
def _criterio(cid, fuerza="decisivo", estado="activo"):
    return Criterio(id=cid, nombre=f"Criterio {cid}", estado=estado, fuente="Art. X",
                    cuerpo="…", fuerza=fuerza)


def _factor(cid, favorece, fuerza="decisivo", estado="activo"):
    return Factor(cid, cid, APLICA, favorece, ["H-1"], "", fuerza, estado)


class ReglaDeResolucionTest(unittest.TestCase):

    def test_ramas(self):
        casos = [
            ([_factor("A", "usuario")], None, "FUNDADO", "decisivo_usuario"),
            ([_factor("A", "empresa")], None, "INFUNDADO", "decisivo_empresa"),
            ([_factor("A", "usuario"), _factor("B", "empresa")], None, None, "decisivos_en_conflicto"),
            ([_factor("A", "revision")], None, None, "criterio_pide_revision"),
            ([_factor("A", "usuario", "indicio")], "INFUNDADO", "INFUNDADO", "sin_decisivos"),
            ([_factor("A", "usuario", "indicio")], "FUNDADO", None, "fundado_solo_con_indicios"),
            ([], None, "INFUNDADO", "sin_decisivos"),
        ]
        for factores, propuesta, veredicto, rama in casos:
            with self.subTest(rama=rama, propuesta=propuesta):
                obtenido, regla, _ = resolver(factores, propuesta)
                self.assertEqual((obtenido, regla), (veredicto, rama))

    def test_criterio_por_confirmar_emite_con_advertencia(self):
        veredicto, _, motivos = resolver([_factor("VPA-01", "usuario", estado="por_confirmar")], None)
        self.assertEqual(veredicto, "FUNDADO")
        self.assertEqual(motivos[0].codigo, "CRITERIO_POR_CONFIRMAR")


class VerificadorTest(unittest.TestCase):

    def setUp(self):
        self.criterios = {c: _criterio(c) for c in ("PRU-01", "LEC-02", "ATI-01")}
        self.hechos = {h.id: h for h in hechos_del_caso(_caso_252396())}
        self.hechos["H-tl-03"] = ProblemaNormado(tipo="lecturaMesReclamado", detalle="…", id="H-tl-03")

    def test_respuesta_valida(self):
        factores, errores = verificar(_respuesta_fundado(), self.criterios, self.hechos)
        self.assertEqual(errores, [])
        self.assertEqual({f.criterio: f.aplica for f in factores},
                         {"PRU-01": "aplica", "LEC-02": "no_aplica", "ATI-01": "no_aplica"})

    def test_errores_detectados(self):
        respuesta = {"factores": [
            {"criterio": "XXX-99", "aplica": "aplica", "hechos": ["H-tl-03"], "favorece": "usuario"},
            {"criterio": "LEC-02", "aplica": "aplica", "hechos": ["H-zz-01"], "favorece": "usuario"},
            {"criterio": "PRU-01", "aplica": "aplica", "hechos": ["H-caso-02"], "favorece": "nadie"},
        ]}
        _, errores = verificar(respuesta, self.criterios, self.hechos)
        texto = "\n".join(errores)
        self.assertIn('"XXX-99" no existe', texto)
        self.assertIn("H-zz-01", texto)
        self.assertIn("LEC-02: aplica, pero no cita ningún hecho", texto)
        self.assertIn("PRU-01: aplica, pero \"favorece\"", texto)
        self.assertIn("la alegación del usuario H-caso-01", texto)


class PasoDictamenTest(unittest.TestCase):

    def test_reintenta_una_vez_con_la_critica(self):
        router = RouterGuion({"factores": [{"criterio": "INVENTADO-01", "aplica": "aplica"}]},
                             _respuesta_fundado())
        dictamen = PasoDictamen(router, "m").dictaminar(_caso_252396())
        self.assertEqual(dictamen.intentos, 2)
        self.assertEqual(dictamen.veredicto, "FUNDADO")
        self.assertEqual(dictamen.regla, "decisivo_usuario")
        critica = router.mensajes_json[1][1].contenido
        self.assertIn("Tu respuesta anterior tuvo estos problemas", critica)
        self.assertIn("INVENTADO-01", critica)
        # el contexto del dictamen trae la alegación y la prueba faltante
        self.assertIn("[H-caso-01] El usuario alega", router.mensajes_json[0][1].contenido)
        self.assertIn("ALEGACIONES del usuario", router.mensajes_json[0][1].contenido)

    def test_pide_un_tope_de_respuesta_propio(self):
        router = RouterGuion(_respuesta_fundado())
        PasoDictamen(router, "m").dictaminar(_caso_252396())
        self.assertEqual(router.max_tokens, 4000)

    def test_una_respuesta_cortada_no_gasta_el_reintento_de_contenido(self):
        """Lo que pasó en el 252629: el primer JSON llegó cortado por el tope de
        tokens y consumió el único reintento; el segundo falló por contenido y
        el caso quedó sin decisión. Ahora son contadores separados."""
        cortada = '{"factores": [{"criterio": "PRU-01", "aplica": "aplica", "hechos": ["H-caso'
        con_error = {"factores": [{"criterio": "INVENTADO-01", "aplica": "aplica"}]}
        router = RouterGuion(cortada, con_error, _respuesta_fundado())
        dictamen = PasoDictamen(router, "m").dictaminar(_caso_252396())

        self.assertEqual(dictamen.intentos, 3)
        self.assertEqual(dictamen.veredicto, "FUNDADO")
        tras_corte = router.mensajes_json[1][1].contenido
        self.assertIn("se cortó antes de cerrar el JSON", tras_corte)
        self.assertNotIn("El JSON no es válido", tras_corte)
        self.assertIn("INVENTADO-01", router.mensajes_json[2][1].contenido)

    def test_dos_respuestas_cortadas_dejan_el_caso_sin_decision(self):
        cortada = '{"factores": [{"criterio": "PRU-01"'
        dictamen = PasoDictamen(RouterGuion(cortada, cortada), "m").dictaminar(_caso_252396())
        self.assertIsNone(dictamen.veredicto)
        self.assertEqual(dictamen.intentos, 2)
        self.assertEqual(dictamen.motivos[0].codigo, "DICTAMEN_INVALIDO")
        self.assertIn("se cortó", dictamen.motivos[0].descripcion)

    def test_dos_respuestas_invalidas_dejan_el_caso_sin_decision(self):
        dictamen = PasoDictamen(RouterGuion("no es json", "tampoco"), "m").dictaminar(_caso_252396())
        self.assertIsNone(dictamen.veredicto)
        self.assertEqual(dictamen.estado, "error_evaluacion")
        self.assertEqual(dictamen.motivos[0].codigo, "DICTAMEN_INVALIDO")


MOTIVO_252629 = (
    "NO ESTOY CONFORME CON LE COBRO DEL RECIBO DE SETIEMBRE DEL 2026, YA QUE MIS CONSUMOS SON "
    "EN BASE A 35 M3 APROXIMADAMENTE Y ESO LO PUEDEN VER EN EL HISTORIAL DE MIS CONSUMOS, RAZON "
    "POR LA QUE SOLICITO QUE REALICEN LAS INSPECCIONES QUE CORRESPONDA EN EL HORARIO DE ABASTECIMIENTO."
)


def _caso_252629() -> InformeAtencion:
    """Datos reales del 252629: consumo normal (54 frente a 52 m³), sin fugas,
    servicio discontinuo pero con VPA operativa y sin interrupciones."""
    informe = _caso_252396("252629")
    informe.datos_reclamo.motivo_reclamo = MOTIVO_252629
    informe.bloques = [
        BloqueMedio("tarjeta_lectura", "Tarjeta de Lecturas", {}, "", [], [
            ProblemaNormado(tipo="lecturaMesReclamado", clase="constatacion", id="H-tl-01",
                            detalle="54 m³ frente a 52 m³", valor={"atipico": False}),
        ]),
        BloqueMedio("inspeccion_externa", "Inspección Externa", {}, "", [], [
            ProblemaNormado(tipo="fugasInspeccionExterna", clase="constatacion", id="H-ie-02",
                            detalle="no se detectaron fugas", valor={"hay_fuga": False, "ubicacion": None}),
        ]),
        BloqueMedio("tecnico_operacional", "Informe Técnico Operacional", {}, "", [], [
            ProblemaNormado(tipo="horarioAbastecimiento", clase="constatacion", id="H-to-01",
                            detalle="servicio discontinuo", valor={"continuo": False}),
            ProblemaNormado(tipo="interrupcionesPeriodo", clase="constatacion", id="H-to-02",
                            detalle="sin interrupciones", valor={"hubo": False}),
            ProblemaNormado(tipo="vpaZona", clase="constatacion", id="H-to-03",
                            detalle="VPA operativa", valor={"existe": True, "operativa": True}),
        ]),
    ]
    return informe


class Caso252629Test(unittest.TestCase):

    def test_pedir_inspecciones_en_el_horario_no_es_alegar_discontinuidad(self):
        self.assertEqual(hechos_del_caso(_caso_252629()), [])

    def test_no_se_detectaron_fugas_no_es_una_fuga(self):
        hecho, = [h for h in extraer_constataciones("inspeccion_externa", {
            "nroinspeccion": 1, "fechainspeccion": "2026-11-02",
            "fugas": "No se detectaron fugas de agua.", "tipofugas": "No Hay",
        }) if h.tipo == "fugasInspeccionExterna"]
        self.assertEqual(hecho.valor, {"hay_fuga": False, "ubicacion": None})

    def test_el_verificador_rechaza_atipico_cuando_el_hecho_dice_que_no_lo_es(self):
        """Red de seguridad: si un criterio con condición llega a evaluarse y el
        modelo lo marca 'aplica' sin un hecho que la cumpla, se rechaza."""
        informe = _caso_252629()
        hechos = {h.id: h for b in informe.bloques for h in b.hechos}
        criterios = {"ATI-01": Criterio("ATI-01", "Atípico", "por_confirmar", "Art. 92", "…",
                                        fuerza="decisivo",
                                        requiere=("lecturaMesReclamado.atipico=true",))}
        _, errores = verificar({"factores": [
            {"criterio": "ATI-01", "aplica": "aplica", "hechos": ["H-tl-01"], "favorece": "usuario"},
        ]}, criterios, hechos)
        self.assertTrue(any("ATI-01: marcado como aplica, pero ningún hecho citado cumple su condición" in e
                            for e in errores))

    def test_un_criterio_sin_su_condicion_se_descarta_sin_preguntar_al_modelo(self):
        """252629: el consumo tiene atipico=false. ATI-01 y ATI-02 no se envían
        al modelo, y aunque este insista en que ATI-01 aplica (la respuesta
        real, que dejaba el caso en error_evaluacion), quedan como no_aplica."""
        informe = _caso_252629()
        respuesta = {"factores": [
            {"criterio": "ATI-01", "aplica": "aplica", "hechos": ["H-tl-01"], "favorece": "usuario"},
            {"criterio": "LEC-02", "aplica": "no_aplica", "hechos": ["H-tl-01"]},
        ], "veredicto_propuesto": "INFUNDADO", "razonamiento": "Lectura válida."}
        router = RouterGuion(respuesta)
        dictamen = PasoDictamen(router, "m").dictaminar(informe)

        self.assertEqual(dictamen.intentos, 1)
        self.assertEqual((dictamen.veredicto, dictamen.regla), ("INFUNDADO", "sin_decisivos"))
        por_id = {f.criterio: f for f in dictamen.factores}
        for cid in ("ATI-01", "ATI-02"):
            self.assertEqual(por_id[cid].aplica, "no_aplica")
            self.assertIn("lecturaMesReclamado.atipico=true", por_id[cid].explicacion)

        system, usuario = (m.contenido for m in router.mensajes_json[0])
        self.assertNotIn("### ATI-01", system)
        self.assertNotIn("### ATI-02", system)
        self.assertIn("### LEC-02", system)
        self.assertNotIn("atipico=", system + usuario)        # ningún nombre de campo interno
        self.assertNotIn("Solo puede aplicar", system)
        self.assertIn("ya comprobó que estos criterios NO aplican", usuario)
        self.assertIn("ATI-01 · Consumo atípico en el mes reclamado", usuario)
        # El dictamen razona sobre hechos: lleva el rol, no las reglas de estilo.
        self.assertIn("Eres Yumi", system)
        self.assertNotIn("## Cómo escribir", system)

    def test_un_criterio_cuya_condicion_se_cumple_si_se_evalua(self):
        informe = _caso_252629()
        informe.bloques[0].hechos[0].valor = {"atipico": True}
        router = RouterGuion({"factores": [], "veredicto_propuesto": "INFUNDADO"})
        dictamen = PasoDictamen(router, "m").dictaminar(informe)
        self.assertIn("### ATI-01", router.mensajes_json[0][0].contenido)
        self.assertEqual({f.criterio: f.aplica for f in dictamen.factores}["ATI-01"], "no_evaluado")

    def test_vpa_01_necesita_que_no_haya_vpa_y_haya_discontinuidad(self):
        criterio = Criterio("VPA-01", "VPA", "activo", "Art. 75", "…", fuerza="decisivo", requiere=(
            "vpaZona.existe=false & horarioAbastecimiento.continuo=false",
            "vpaZona.existe=false & interrupcionesPeriodo.hubo=true"))
        sin_vpa = ProblemaNormado(tipo="vpaZona", detalle="", valor={"existe": False})
        con_vpa = ProblemaNormado(tipo="vpaZona", detalle="", valor={"existe": True})
        discontinuo = ProblemaNormado(tipo="horarioAbastecimiento", detalle="", valor={"continuo": False})
        continuo = ProblemaNormado(tipo="horarioAbastecimiento", detalle="", valor={"continuo": True})
        from app.src.application.usecase.pasos.dictamen import cumple_requisito
        self.assertTrue(cumple_requisito(criterio, [sin_vpa, discontinuo]))
        self.assertFalse(cumple_requisito(criterio, [con_vpa, discontinuo]))
        self.assertFalse(cumple_requisito(criterio, [sin_vpa, continuo]))

    def test_explica_que_un_hecho_no_es_un_criterio(self):
        hechos = {h.id: h for h in hechos_del_caso(_caso_252396())}
        _, errores = verificar({"factores": [{"criterio": "H-caso-01", "aplica": "aplica"}]},
                               {"PRU-01": _criterio("PRU-01")}, hechos)
        self.assertTrue(any('"H-caso-01" es un HECHO, no un criterio' in e for e in errores))

    def test_una_alegacion_puede_tratarse_en_la_lista_de_alegaciones(self):
        hechos = {h.id: h for h in hechos_del_caso(_caso_252396())}
        respuesta = {"factores": [{"criterio": "PRU-01", "aplica": "aplica",
                                   "hechos": ["H-caso-02"], "favorece": "usuario"}],
                     "alegaciones": [{"hecho": "H-caso-01", "explicacion": "Sin informe que la descarte."}]}
        _, errores = verificar(respuesta, {"PRU-01": _criterio("PRU-01")}, hechos)
        self.assertEqual(errores, [])


class ConclusionConDictamenTest(unittest.TestCase):

    def test_252396_queda_fundado_redactado_y_persistido(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "yumi.db"
            repo = SqliteCasoRepository(ruta)
            try:
                store = InformeAtencionStore()
                store.configurar_persistencia(repo)
                informe = store.crear_metadata("252396", "24578", _caso_252396().datos_reclamo)
                for bloque in _caso_252396().bloques:
                    store.registrar_bloque("252396", bloque)
                informe = store.obtener("252396")

                respuesta = _respuesta_fundado()
                respuesta["factores"][0]["hechos"].append("H-tl-03")
                router = RouterGuion(respuesta)
                veredicto = PasoConclusion(router, modo="dictamen").concluir_y_asignar(informe)
                store.persistir_cambios()

                self.assertEqual(veredicto, "FUNDADO")
                self.assertEqual(informe.estado_evaluacion, "completada")
                self.assertTrue(informe.conclusion.startswith("En consecuencia"))
                self.assertEqual(informe.dictamen["regla"], "decisivo_usuario")

                con = sqlite3.connect(ruta)
                citados = [f[0] for f in con.execute(
                    "SELECT ah.hecho_id FROM artefacto_hechos ah JOIN artefactos a ON a.id = ah.artefacto_id "
                    "WHERE a.tipo = 'dictamen' AND a.vigente = 1")]
                con.close()
                recargado = InformeAtencionStore()
                recargado.configurar_persistencia(repo)
                self.assertEqual(recargado.obtener("252396").dictamen["veredicto"], "FUNDADO")
            finally:
                repo.cerrar_conexion()
        tarjeta = next(b for b in informe.bloques if b.medio_id == "tarjeta_lectura")
        self.assertEqual(citados, [tarjeta.hechos[0].id])   # H-caso-* no se enlazan


if __name__ == "__main__":
    unittest.main()
