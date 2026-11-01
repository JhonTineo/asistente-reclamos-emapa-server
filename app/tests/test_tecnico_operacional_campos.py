"""Campos puntuales del informe técnico operacional, hallazgos por reglas y su
ficha en el panel de evidencias. Textos de ejemplo con datos ficticios, con la
misma redacción de los dos formatos reales de EMAPA."""

import unittest
from types import SimpleNamespace

from app.src.application.services.pre_proces.pre_tecnico_operacional import (
    campos_formulario, campos_narrativo,
)
from app.src.application.services.pre_proces.problemas_normalizer import extraer_problemas
from app.src.application.services.informe.evidencias import construir_informe_tecnico
from app.tests.test_evidencias import informe_ejemplo
from app.src.core.model.informe_atencion import BloqueMedio

NARRATIVO = """INFORME N° 1000-2025-EMAPA-SM-SA-OAC-ODR-IO
FECHA : 02 DE AGOSTO DE 2025
I) Antecedentes
La Oficina de Atención al Cliente solicitó la verificación del servicio.
II) Análisis
Ubicación y horario de abastecimiento:
Según el análisis realizado, se confirma que la conexión en cuestión se encuentra
ubicada en el JR. EJEMPLO 123, en el distrito de Tarapoto, con el Código de
Suministro N° 1 – Sector 10 R-2500 (QGIS). De acuerdo con los lineamientos del
TRASS, el horario de abastecimiento establecido para esta conexión es de 00:00AM
A 11:20AM – 16:40PM A 24:00PM.
Continuidad del servicio:
Durante el periodo de junio de 2025 no se han producido interrupciones del servicio
de agua potable fuera del horario de abastecimiento. Se adjunta evidencia.
Existencia de válvula de aire:
Se pudo constatar que existe la presencia de UNA (01) válvula de aire operativa en
el sector mencionado. Dado que se encuentra en una zona media, como se evidencia en
el plano de curvas de nivel adjunto.
III) Conclusiones y recomendaciones
Se concluye que el informe operacional fue atendido.
Para su conocimiento y fines correspondientes."""

FORMULARIO = """INFORME TÉCNICO OPERACIONAL
N° INFORME: 3000
FECHA INFORME: 14/10/2026
DATOS DEL PREDIO
UBICACION: JR. EJEMPLO 456 – TARAPOTO
DATOS DEL RECLAMO
MESES RECLAMADOS: SETIEMBRE-2026
HORA DE SUMINISTRO: 2:40 A 8:20 - 17:30 A 21:50
FUENTE DE ABASTECIMIENTO: S10-R2500 m3 – ZONA ALTA
REPORTE DE INTERRUPCIONES
Reporte de presion
PROMEDIO HISTORICO DEL AÑO – 41.103 M.C. A (TP-MP25)
Observaciones
 -
Conclusiones
Se concluye que el informe operacional fue atendido.
Nota: Las presiones corresponden al periodo facturado."""

CASILLAS = {
    "En el periodo reclamado hubo interrupciones en el abastecimiento": "SI",
    "Se adjunta reporte de interrupciones en las fuentes de abastecimiento en los meses reclamados": "SI",
    "Existencia de VPA en la zona": "No hay VPA",
    "Estado de la VPA": "No determinada (sin marca X legible o marcas múltiples)",
    "Se anexa plano de curvas de nivel": "SI",
}


class TestCampos(unittest.TestCase):
    def test_narrativo(self):
        c = campos_narrativo(NARRATIVO)
        self.assertEqual(c["numero_informe"], "1000-2025-EMAPA-SM-SA-OAC-ODR-IO")
        self.assertEqual(c["ubicacion"], "JR. EJEMPLO 123")
        self.assertEqual(c["horario_abastecimiento"], "00:00AM A 11:20AM – 16:40PM A 24:00PM")
        self.assertEqual(c["zona"], "MEDIA")
        self.assertEqual(c["interrupciones"], "NO")
        self.assertEqual(c["existe_valvula_aire"], "SI")
        self.assertEqual(c["estado_valvula_aire"], "Operativa")
        self.assertIn("atendido", c["conclusiones"])
        self.assertNotIn("conocimiento", c["conclusiones"])

    def test_formulario(self):
        c = campos_formulario(FORMULARIO, CASILLAS)
        self.assertEqual(c["numero_informe"], "3000")
        self.assertEqual(c["meses_reclamados"], "SETIEMBRE-2026")
        self.assertEqual(c["zona"], "ALTA")
        self.assertEqual(c["interrupciones"], "SI")
        self.assertEqual(c["existe_valvula_aire"], "NO")
        self.assertIsNone(c["estado_valvula_aire"])
        self.assertAlmostEqual(c["presion_mca"], 41.103)
        self.assertIsNone(c["observaciones"])          # "-" equivale a vacío
        self.assertIn("atendido", c["conclusiones"])


class TestHallazgosYFicha(unittest.TestCase):
    def test_hallazgos(self):
        c = campos_formulario(FORMULARIO, CASILLAS)
        tipos = [p.tipo for p in extraer_problemas("tecnico_operacional", SimpleNamespace(campos=c))]
        self.assertEqual(tipos, ["interrupcionAbastecimiento", "sinValvulaAire"])
        sin = campos_narrativo(NARRATIVO)
        self.assertEqual(extraer_problemas("tecnico_operacional", SimpleNamespace(campos=sin)), [])
        self.assertEqual(extraer_problemas("tecnico_operacional", SimpleNamespace(campos={})), [])

    def test_ficha_en_evidencias(self):
        inf = informe_ejemplo()
        self.assertIsNone(construir_informe_tecnico(inf))
        inf.bloques.append(BloqueMedio("tecnico_operacional", "Informe Técnico Operacional",
                                       {"formato": "formulario", "campos": campos_formulario(FORMULARIO, CASILLAS)},
                                       "resumen"))
        ficha = construir_informe_tecnico(inf)
        self.assertEqual(ficha["numero_informe"], "3000")
        self.assertEqual(ficha["alertas"], 2)            # interrupciones + sin VPA en zona alta
        puntos = {p["punto"]: p["resultado"] for p in ficha["puntos"]}
        self.assertEqual(puntos["Presión promedio"], "41.103 m.c.a.")


if __name__ == "__main__":
    unittest.main()
