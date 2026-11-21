"""Base normativa versionada, catálogo (índice / leer / BM25 / documento) y
fundamentación por índice con citas verificadas."""

import json
import unittest

from app.src.application.services.normativa.catalogo import CatalogoNormativo
from app.src.application.services.normativa.importar import (
    dispositivos_de, id_unidad, importar_todo,
)
from app.src.application.usecase.pasos.fundamentacion import (
    PasoFundamentacion, verificar_citas,
)
from app.src.core.model.informe_atencion import ProblemaNormado
from app.src.infrastructure.adapters.persistencia.sqlite_normativa_repository import (
    SqliteNormativaRepository,
)

NORMA = {"id": "RC", "nombre": "Reglamento de Calidad", "coleccion": "sunass_reglamento"}


def _unidades():
    ruta = "TÍTULO V > CAPÍTULO 2: FACTURACIÓN"
    return [
        {"id": "RC.91", "tipo": "articulo", "articulo": "91", "orden": 1, "ruta": ruta,
         "titulo": "Consideraciones en la facturación basada en diferencia de lecturas",
         "texto": "", "nota": "(Texto según el artículo 87 de la RCD N.o 011-2007-SUNASS-CD)",
         "dispositivos": ["RCD 011-2007-SUNASS-CD"]},
        {"id": "RC.91.e", "tipo": "literal", "articulo": "91", "numeral": "91 e)", "padre_id": "RC.91",
         "orden": 2, "ruta": ruta,
         "texto": "e) La empresa prestadora que instale medidores por primera vez informará al usuario."},
        {"id": "RC.91.f", "tipo": "literal", "articulo": "91", "numeral": "91 f)", "padre_id": "RC.91",
         "orden": 3, "ruta": ruta,
         "texto": "f) Diferencia de lecturas válida.- el período entre las lecturas no será menor a "
                  "veintiocho (28) ni mayor a treinta y dos (32) días calendario."},
        {"id": "RC.102", "tipo": "articulo", "articulo": "102", "orden": 4, "ruta": ruta,
         "titulo": "Intereses moratorios", "texto": "Se cobran intereses moratorios por pago fuera de plazo."},
    ]


def _catalogo():
    repo = SqliteNormativaRepository(":memory:")
    repo.importar_norma(NORMA, _unidades())
    return repo, CatalogoNormativo(repo)


class TestRepositorioVersionado(unittest.TestCase):
    def test_nueva_version_cambia_solo_esa_unidad_y_guarda_historial(self):
        repo, _ = _catalogo()
        repo.nueva_version("RC.91.f", "f) Texto modificado.", vigente_desde="2026-01-01",
                           dispositivos=["RCD 001-2026-SUNASS-CD"], origen="modificatoria")
        self.assertEqual(repo.unidad("RC.91.f").texto, "f) Texto modificado.")
        self.assertIn("Diferencia de lecturas", repo.unidad("RC.91.f", fecha="2025-06-01").texto)
        self.assertIn("medidores por primera vez", repo.unidad("RC.91.e").texto)
        historial = repo.historial("RC.91.f")
        self.assertEqual([h["estado"] for h in historial], ["reemplazado", "vigente"])
        self.assertEqual(historial[0]["vigente_hasta"], "2026-01-01")

    def test_unidad_inexistente(self):
        repo, _ = _catalogo()
        with self.assertRaises(KeyError):
            repo.nueva_version("RC.999", "x", vigente_desde=None)


class TestCatalogo(unittest.TestCase):
    def setUp(self):
        self.repo, self.cat = _catalogo()

    def test_indice_lista_articulos_con_sus_literales(self):
        indice = self.cat.indice()
        self.assertIn("- RC.91: Consideraciones en la facturación", indice)
        self.assertIn("(e) a f))", indice)
        self.assertNotIn("RC.91.f", indice)

    def test_leer_articulo_omite_intro_vacia(self):
        self.assertEqual([u.id for u in self.cat.leer("RC.91")], ["RC.91.e", "RC.91.f"])
        self.assertEqual(self.cat.leer("RC.999"), [])

    def test_busqueda_lexica_encuentra_la_frase_exacta(self):
        ids = [u.id for u, _ in self.cat.buscar_texto("veintiocho treinta y dos días lecturas")]
        self.assertEqual(ids[0], "RC.91.f")

    def test_documento_reconstruido_conserva_orden_y_nota(self):
        doc = self.cat.documento("RC")
        self.assertLess(doc.index("e) La empresa"), doc.index("f) Diferencia"))
        self.assertIn("Texto según el artículo 87", doc)

    def test_recargar_refleja_una_modificacion(self):
        self.repo.nueva_version("RC.102", "Intereses moratorios: nuevo texto.", vigente_desde="2026-02-01")
        self.cat.recargar()
        self.assertIn("nuevo texto", self.cat.leer("RC.102")[0].texto)


class TestImportacion(unittest.TestCase):
    def test_ids_estables(self):
        self.assertEqual(id_unidad("RC", "91", None), "RC.91")
        self.assertEqual(id_unidad("RC", "92", "92.3"), "RC.92.3")
        self.assertEqual(id_unidad("RC", "91", "91 f)"), "RC.91.f")

    def test_dispositivos_de_la_nota(self):
        nota = ("(Texto según el artículo 87 de la RCD N.o 011-2007-SUNASS-CD, modificado por las "
                "RCD Nros. 088-2007-SUNASS- CD y 034-2023-SUNASS-CD)")
        self.assertEqual(dispositivos_de(nota), [
            "RCD 011-2007-SUNASS-CD", "RCD 088-2007-SUNASS-CD", "RCD 034-2023-SUNASS-CD"])

    def test_importa_los_pdfs_del_repositorio(self):
        repo = SqliteNormativaRepository(":memory:")
        resultado = importar_todo(repo)
        self.assertEqual(set(resultado), {"RC", "RGR"})
        for uid in ("RC.91.f", "RC.92.3", "RGR.14.6", "RGR.33"):
            self.assertIsNotNone(repo.unidad(uid), uid)
        self.assertTrue(repo.unidad("RC.91").dispositivos)


class _Router:
    """Responde la navegación con artículos fijos (y uno inventado)."""
    def __init__(self, respuesta):
        self.respuesta = respuesta

    def generar_json(self, mensajes, modelo_id, esquema=None, **_):
        return self.respuesta


class TestFundamentacionPorIndice(unittest.TestCase):
    def test_navegacion_descarta_ids_inventados_y_suma_lexicos(self):
        _, cat = _catalogo()
        router = _Router(json.dumps({"hechos": [{"hecho": 0, "articulos": ["RC.91", "RC.500"]}]}))
        paso = PasoFundamentacion(qdrant=None, llm_router=router, metodo="indice", catalogo=cat)
        problema = ProblemaNormado(tipo="errorConsumo", detalle="Intereses moratorios cobrados")
        candidatos = paso.buscar_articulos(problema)
        ids = [c["id"] for c in candidatos]
        self.assertEqual(ids[:2], ["RC.91.e", "RC.91.f"])   # del índice, en orden
        self.assertIn("RC.102", ids)                       # léxico
        self.assertNotIn("RC.500", ids)
        self.assertEqual(candidatos[0]["payload"]["numeral"], "91 e)")

    def test_si_la_navegacion_falla_quedan_los_lexicos(self):
        _, cat = _catalogo()
        paso = PasoFundamentacion(qdrant=None, llm_router=_Router("no es json"), metodo="indice",
                                  catalogo=cat)
        problema = ProblemaNormado(tipo="mora", detalle="Intereses moratorios cobrados")
        self.assertEqual(paso.buscar_articulos(problema)[0]["id"], "RC.102")


class TestVerificarCitas(unittest.TestCase):
    def _problema(self):
        p = ProblemaNormado(tipo="lecturaMesReclamado", detalle="30 días entre lecturas")
        p.articulos = [{"article": "91", "numeral": "91 f)", "aplica": True,
                        "texto": "f) Diferencia de lecturas válida.- el período entre las lecturas no será "
                                 "menor a veintiocho (28) ni mayor a treinta y dos (32) días calendario."},
                       {"article": "93", "numeral": "93.2", "aplica": False, "texto": "otro"}]
        return [p]

    def test_cita_correcta(self):
        texto = ("Conforme al inciso f) del artículo 91, «el período entre las lecturas no será menor a "
                 "veintiocho (28)», y la lectura cumple.")
        self.assertEqual(verificar_citas(texto, self._problema()), [])

    def test_articulo_no_aplicable_y_frase_inventada(self):
        texto = ("Según el artículo 93 y el Art. 91, «la empresa debe facturar siempre el promedio histórico».")
        errores = verificar_citas(texto, self._problema())
        self.assertEqual(len(errores), 2)
        self.assertIn("artículo 93", errores[0])


if __name__ == "__main__":
    unittest.main()
