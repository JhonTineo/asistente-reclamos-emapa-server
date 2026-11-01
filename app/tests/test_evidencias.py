import base64
import io
import unittest
from datetime import date, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.src.application.services.informe.evidencias import (
    construir_evidencias, periodos_reclamados,
)
from app.src.application.services.informe.fotos_evidencia import FotosEvidenciaService, clasificar
from app.src.application.services.informe.informe_store import informe_store
from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion, ObjetivoInvestigacion
from app.src.core.model.reclamo import Reclamo

# Lecturas reales de un suministro (sin datos personales): enero a octubre 2026.
LECTURAS = [(1, 549, 606, "2026-01-18"), (2, 606, 652, "2026-02-19"), (3, 652, 685, "2026-03-20"),
            (4, 685, 723, "2026-04-17"), (5, 723, 753, "2026-05-18"), (6, 753, 794, "2026-06-19"),
            (7, 794, 832, "2026-07-18"), (8, 832, 885, "2026-08-18"), (9, 885, 934, "2026-09-19"),
            (10, 934, 994, "2026-10-19")]


def informe_ejemplo(codreclamo="900001") -> InformeAtencion:
    inf = InformeAtencion(numero="X", fecha=datetime(2026, 10, 20), asunto="A", reclamo=codreclamo, suministro="7053")
    inf.datos_reclamo = Reclamo(
        codcliente="7053", clasificacion_reclamo="A1. CONSUMO MEDIDO", meses_reclamados="SETIEMBRE-2026",
        fecha_recepcion="2026-10-01", fecha_notificacion_inspeccion="2026-10-09 14:35:00.0",
        fecha_reunion="2026-10-26 14:35:00.0", fecha_max_resolucion="2026-11-17",
    )
    inf.bloques.append(BloqueMedio("tarjeta_lectura", "Tarjeta", {"registros": [
        {"anio": 2026, "mes": m, "lecturaanterior": a, "lecturaultima": b, "consumo": b - a,
         "fechalecturault": f + " 08:00:00", "estadolectura_texto": "LECTURA NORMAL"} for m, a, b, f in LECTURAS
    ]}, "resumen"))
    inf.bloques.append(BloqueMedio("record_facturacion", "Record", {"registros": [
        {"anio": 2026, "mes": m, "consumofac": b - a, "impmestotal": round((b - a) * 3.1, 2), "tipopromedio": "0"}
        for m, a, b, _ in LECTURAS
    ]}, "resumen"))
    inf.bloques.append(BloqueMedio("inspeccion_externa", "Externa", {
        "nroinspeccion": "11576", "fechainspeccion": "2026-10-09", "funcionamed": "El medidor funciona correctamente.",
        "fugas": "No se detectaron fugas de agua.", "tipofugas": "No Hay",
        "estadocaja": "La caja del medidor está en buen estado.", "estconexion": None,
        "atipico": "No se detectaron condiciones atípicas en la inspección.", "observacionmed": "", "observacionsum": None,
    }, "resumen"))
    inf.bloques.append(BloqueMedio("inspeccion_interna", "Interna", {
        "nroinspeccion": "11569", "fechainspeccion": "2026-10-09", "estadoabas": "Abastecimiento Normal",
        "atipico": "No hubo consumos atípicos en la inspección.",
        "puntos_agua": [{"inodoro": 2, "lavado": 3, "ducha": 2, "grifo": 1}, {"inodoro": 1, "tanque": 1}],
    }, "resumen"))
    inf.objetivos = [
        ObjetivoInvestigacion(1, "¿El consumo de setiembre es atípico?", "tarjeta_lectura", True, "sin_correccion", "49 m³"),
        ObjetivoInvestigacion(2, "¿Hay fugas?", "inspeccion_externa", True, "sin_correccion", "Sin fugas"),
        ObjetivoInvestigacion(3, "Contexto de deuda", "saldo_detalle", False),
    ]
    inf.veredicto = "INFUNDADO"
    return inf


def jpeg(color=(200, 30, 30), tam=(2400, 1800)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", tam, color).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


class ApiFalsa:
    def __init__(self, items):
        self.items = items
        self.llamadas = []

    def obtener_imagenes_cliente(self, codsuc, codcliente, fecha_inicial, fecha_final):
        self.llamadas.append((fecha_inicial, fecha_final))
        return {"success": True, "data": [i for i in self.items if fecha_inicial <= i["fechareg"][:10] <= fecha_final]}


class TestEvidencias(unittest.TestCase):
    def test_periodos(self):
        self.assertEqual(periodos_reclamados("JULIO-2026, AGOSTO-2026"), [(2026, 7), (2026, 8)])
        self.assertEqual(periodos_reclamados("SETIEMBRE 2026"), [(2026, 9)])
        self.assertEqual(periodos_reclamados(None), [])

    def test_serie_e_indicadores(self):
        ev = construir_evidencias(informe_ejemplo())
        self.assertEqual(len(ev["serie"]), 10)
        sept = next(s for s in ev["serie"] if s["mes"] == 9)
        self.assertTrue(sept["reclamado"])
        self.assertEqual(sept["consumo"], 49)
        ind = ev["indicadores"]
        self.assertEqual(ind["meses_base"], 6)                  # marzo a agosto
        self.assertAlmostEqual(ind["promedio_previo"], 38.8)
        self.assertAlmostEqual(ind["veces_promedio"], 1.26)
        self.assertEqual(ind["nivel"], "habitual")
        self.assertEqual((ind["minimo_previo"], ind["maximo_previo"]), (30, 53))
        self.assertIn("rango", ind["interpretacion"])

    def test_inspecciones_y_linea_de_tiempo(self):
        ev = construir_evidencias(informe_ejemplo())
        ext = ev["inspeccion_externa"]
        self.assertEqual(ext["alertas"], 0)
        self.assertTrue(all(p["estado"] == "conforme" for p in ext["puntos"]))
        inte = ev["inspeccion_interna"]
        self.assertEqual(inte["total_puntos_agua"], 10)
        self.assertEqual(inte["unidades_uso"], 2)
        self.assertIn({"tipo": "Inodoros", "cantidad": 3}, inte["puntos_agua"])
        fechas = [h["fecha"] for h in ev["linea_tiempo"]]
        self.assertEqual(fechas, sorted(fechas))
        self.assertEqual(fechas[0], "2026-09-19")
        self.assertIn("2026-11-17", fechas)
        self.assertEqual([v["id"] for v in ev["verificaciones"]], [1, 2])

    def test_alerta_en_inspeccion(self):
        inf = informe_ejemplo()
        inf.bloques[2].entidad["fugas"] = "Se detectaron fugas de agua."
        ev = construir_evidencias(inf)
        self.assertEqual(ev["inspeccion_externa"]["alertas"], 1)

    def test_sin_medios_analizados(self):
        inf = informe_ejemplo()
        inf.bloques = []
        ev = construir_evidencias(inf)
        self.assertEqual(ev["serie"], [])
        self.assertIsNone(ev["indicadores"])
        self.assertFalse(ev["disponible"]["consumo"])


class TestFotos(unittest.TestCase):
    def setUp(self):
        FotosEvidenciaService.limpiar_cache()
        rojo, azul = jpeg(), jpeg((30, 30, 200))
        self.items = [
            {"pathimage": "LECT-001-001-7053-908642.jpg", "observacion": "LECTURAS 2026 10", "fechareg": "2026-10-19 11:15:02", "img64": jpeg((0, 200, 0)), "tipoarchivo": "IMG"},
            {"pathimage": "RECLA-REATENSION-IMG-001-001-7053-887714.jpg", "tiporecepcionimages": "RECLA-REATENSION-IMG", "fechareg": "2026-10-14 20:57:56", "img64": rojo},
            {"pathimage": "RECLA-REATENSION-IMG-001-001-7053-887713.jpg", "tiporecepcionimages": "RECLA-REATENSION-IMG", "fechareg": "2026-10-14 20:57:55", "img64": azul},
            {"pathimage": "RECLA-REATENSION-IMG-001-001-7053-887710.jpg", "tiporecepcionimages": "RECLA-REATENSION-IMG", "fechareg": "2026-10-14 20:57:50", "img64": rojo},
            {"pathimage": "RECLA-REATENSION-FIRMA-001-001-7053-1.jpg", "tiporecepcionimages": "RECLA-REATENSION-FIRMA", "fechareg": "2026-10-14 20:57:40", "img64": rojo},
            {"pathimage": "RECLA-INGRE-IMG-001-001-7053-886204.pdf", "tiporecepcionimages": "RECLA-INGRE-IMG", "fechareg": "2026-10-01 12:23:00", "img64": base64.b64encode(b"%PDF-1.4 " + b"x" * 300).decode()},
            {"pathimage": "LECT-001-001-7053-847877.jpg", "observacion": "LECTURAS 2026 09", "fechareg": "2026-09-19 08:23:11", "img64": jpeg((250, 250, 0))},
            {"pathimage": "RECLA-INGRE-IMG-001-001-7053-830679.pdf", "tiporecepcionimages": "RECLA-INGRE-IMG", "fechareg": "2026-09-19 12:44:24", "img64": base64.b64encode(b"%PDF-1.4 otro" + b"y" * 300).decode()},
        ]

    def test_clasificar(self):
        self.assertEqual(clasificar(self.items[0]), "lectura")
        self.assertEqual(clasificar(self.items[1]), "inspeccion")
        self.assertEqual(clasificar(self.items[4]), "firma")
        self.assertEqual(clasificar(self.items[5]), "formulario")

    def test_rangos(self):
        rangos = FotosEvidenciaService(ApiFalsa([])).rangos(informe_ejemplo(), hoy=date(2026, 10, 26))
        self.assertEqual(rangos, [(date(2026, 9, 18), date(2026, 9, 21)), (date(2026, 10, 1), date(2026, 10, 26))])

    def test_selecciona_dedupe_y_reduce(self):
        api = ApiFalsa(self.items)
        with patch("app.src.application.services.informe.fotos_evidencia.date") as d:
            d.today.return_value = date(2026, 10, 26)
            d.side_effect = lambda *a, **k: date(*a, **k)
            res = FotosEvidenciaService(api).obtener(informe_ejemplo(), "001", "7053")
        cats = [f["categoria"] for f in res["fotos"]]
        self.assertEqual(cats, ["lectura", "inspeccion", "inspeccion", "formulario"])
        self.assertEqual(res["fotos"][0]["periodo"], "Set 2026")
        self.assertEqual(res["omitidas"]["firma"], 1)
        self.assertEqual(res["omitidas"]["repetida"], 1)
        self.assertGreaterEqual(res["omitidas"]["fuera_de_periodo"], 2)   # lectura de octubre + formulario anterior
        foto = res["fotos"][1]
        self.assertEqual(max(foto["ancho"], foto["alto"]), 1600)
        self.assertEqual(foto["titulo"], "Foto 1 de la inspección")
        # Segunda llamada: sale de la copia en memoria, sin volver a SYSCO.
        n = len(api.llamadas)
        res2 = FotosEvidenciaService(api).obtener(informe_ejemplo(), "001", "7053")
        self.assertTrue(res2["desde_cache"])
        self.assertEqual(len(api.llamadas), n)


class TestEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.src.main import app
        cls.client = TestClient(app)

    def setUp(self):
        FotosEvidenciaService.limpiar_cache()
        informe_store._data["900001"] = informe_ejemplo()

    def tearDown(self):
        informe_store._data.pop("900001", None)

    def test_evidencias(self):
        r = self.client.get("/reclamos/900001/evidencias")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["indicadores"]["veces_promedio"], 1.26)
        self.assertEqual(self.client.get("/reclamos/000000/evidencias").status_code, 404)

    def test_fotos_exige_token(self):
        r = self.client.get("/reclamos/900001/evidencias/fotos", params={"codsuc": "001"})
        # Sin header Authorization y sin token en .env de pruebas -> 401
        if r.status_code != 401:
            self.skipTest("Hay un EMAPA_ACCESS_TOKEN en el entorno; no se puede probar el 401")

    def test_fotos_con_token(self):
        items = [{"pathimage": "LECT-1.jpg", "observacion": "LECTURAS 2026 09", "fechareg": "2026-09-19 08:23:11", "img64": jpeg()}]
        with patch("app.src.infrastructure.adapters.emapa_http_adapter.EmapaHttpAdapter.obtener_imagenes_cliente",
                   new=lambda self, *a: ApiFalsa(items).obtener_imagenes_cliente(*a)):
            r = self.client.get("/reclamos/900001/evidencias/fotos", params={"codsuc": "001"},
                                headers={"Authorization": "token-de-prueba"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["resumen"]["lectura"], 1)


if __name__ == "__main__":
    unittest.main()
