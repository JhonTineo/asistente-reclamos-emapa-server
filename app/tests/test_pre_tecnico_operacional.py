import unittest
import pymupdf
from app.src.application.services.pre_proces.pre_tecnico_operacional import PreTecnicoOperacionalService, _respuesta_casilla, _es_formulario

class PreTecnicoTests(unittest.TestCase):
    def test_narrativo_multipagina(self):
        r = PreTecnicoOperacionalService()._extraer_narrativo(['II) Analisis Ubicacion y horario de abastecimiento:\nServicio de 8 a 12.', 'Sin interrupciones.\nIII) Conclusiones\nEXCLUIR'], 'test.pdf')
        self.assertEqual(r.paginas, [1, 2])
        self.assertIn('Sin interrupciones.', r.texto_extraido)
        self.assertNotIn('EXCLUIR', r.texto_extraido)

    def test_formulario(self):
        texto = 'INFORME TECNICO OPERACIONAL\nDATOS DEL PREDIO\nREPORTE DE INTERRUPCIONES\nREPORTE DE VALVULAS DE PURGA DE AIRE\nReporte de presion\nPROMEDIO: 41.103'
        self.assertTrue(_es_formulario(texto))
        self.assertFalse(_es_formulario('Otro documento'))
        with pymupdf.open() as doc:
            doc.new_page().insert_text((40,40), texto)
            doc.new_page().insert_text((40,40), 'Anexo')
            r = PreTecnicoOperacionalService()._extraer_formulario(doc, 'test.pdf')
        self.assertEqual(r.formato, 'formulario')
        self.assertEqual(r.paginas, [1])
        self.assertIn('41.103', r.texto_extraido)
        self.assertIn('No determinada', r.texto_extraido)
        self.assertNotIn('Anexo', r.texto_extraido)

    def test_casillas(self):
        for marcas, esperado in [([], 'No determinada'), ([350], 'Operativa'), ([490], 'Inoperativa'), ([350, 490], 'No determinada')]:
            with self.subTest(marcas=marcas), pymupdf.open() as doc:
                p = doc.new_page()
                p.insert_text((40,100), 'Estado de la VPA')
                p.insert_text((290,100), 'Operativa')
                p.insert_text((420,100), 'Inoperativa')
                for x in marcas:
                    p.insert_text((x,100), 'X')
                r = _respuesta_casilla(p, 'Estado de la VPA', ('Operativa','Inoperativa'))
                self.assertTrue(r.startswith(esperado), r)
