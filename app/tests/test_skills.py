"""Skills en Markdown: formato, validación y lo que llega al modelo."""

import os
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from app.src.core.model.skill import SECCION_CRITERIOS, SECCION_LECTURA, SECCION_METODO
from app.src.infrastructure.adapters.skills.skill_file_repository import (
    DIRECTORIO_SKILLS, SkillFileRepository,
)

MEDIOS_CON_SKILL = ("tarjeta_lectura", "inspeccion_interna", "inspeccion_externa", "tecnico_operacional")

SKILL_MINIMA = textwrap.dedent("""\
    ---
    id: medio.prueba
    tipo: medio
    medio: prueba
    titulo: Medio de prueba
    version: 1
    estado: activo
    ---

    ## Qué es
    Un medio para las pruebas.

    ## Cómo leerlo
    Léelo con cuidado.

    ## Criterios de valoración

    ### PRB-01 · Criterio confirmado
    - **Estado:** activo
    - **Fuerza:** decisivo
    - **Fuente:** Art. 1

    **Por qué importa:** explicación del criterio confirmado.

    ### PRB-02 · Criterio por confirmar
    - **Estado:** por_confirmar
    - **Fuerza:** indicio
    - **Fuente:** criterio del especialista
    - **Pendiente:** duda interna que no debe llegar al modelo

    **Por qué importa:** explicación del criterio pendiente.

    ### PRB-03 · Criterio retirado
    - **Estado:** inactivo
    - **Fuerza:** indicio
    - **Fuente:** Art. 2

    **Por qué importa:** ya no se usa.

    ## Preguntas abiertas
    - Pregunta solo para el especialista.
    """)


class SkillsDelRepositorioTest(unittest.TestCase):
    """Los archivos reales de app/src/skills deben cargar sin errores."""

    @classmethod
    def setUpClass(cls):
        cls.repo = SkillFileRepository(DIRECTORIO_SKILLS)

    def test_no_hay_errores_de_formato(self):
        self.assertEqual(self.repo.errores(), [])

    def test_cada_medio_tiene_su_skill_con_lectura_y_criterios(self):
        for medio in MEDIOS_CON_SKILL:
            with self.subTest(medio=medio):
                skill = self.repo.para_medio(medio)
                self.assertIsNotNone(skill)
                self.assertTrue(skill.seccion(SECCION_LECTURA))
                self.assertTrue(skill.criterios_vigentes())

    def test_tipo_consumo_medido_por_codigo_y_por_clasificacion(self):
        por_codigo = self.repo.para_tipo_reclamo(codigo="1")
        por_clasificacion = self.repo.para_tipo_reclamo(clasificacion="A1. CONSUMO MEDIDO")
        self.assertIsNotNone(por_codigo)
        self.assertEqual(por_codigo.id, por_clasificacion.id)
        self.assertTrue(por_codigo.seccion(SECCION_METODO))
        self.assertIsNone(self.repo.para_tipo_reclamo(clasificacion="B9. OTRO"))

    def test_los_criterios_del_especialista_estan_cubiertos(self):
        ids = {c.id for s in self.repo.todas() for c in s.criterios_vigentes()}
        # válvula ausente, válvula inoperativa, atípico, fuga en caja, desabastecimiento
        self.assertLessEqual({"VPA-01", "VPA-02", "ATI-01", "CAJ-01", "INT-01"}, ids)

    def test_todo_criterio_vigente_cita_su_fuente(self):
        for skill in self.repo.todas():
            for c in skill.criterios_vigentes():
                with self.subTest(criterio=c.id):
                    self.assertTrue(c.fuente.strip())


class FormatoDeSkillTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "medios").mkdir()
        (self.dir / "tipos").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def escribir(self, nombre: str, contenido: str) -> Path:
        ruta = self.dir / nombre
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def test_texto_para_el_modelo(self):
        self.escribir("medios/prueba.md", SKILL_MINIMA)
        skill = SkillFileRepository(self.dir).para_medio("prueba")

        texto = skill.render([SECCION_LECTURA, SECCION_CRITERIOS, "Preguntas abiertas"])
        self.assertIn("Léelo con cuidado.", texto)
        self.assertIn("PRB-01 · Criterio confirmado\nFuente: Art. 1", texto)
        self.assertIn("PRB-02 · Criterio por confirmar (por confirmar con el especialista)", texto)
        # Lo inactivo y lo que es solo para personas no llega al modelo.
        self.assertNotIn("PRB-03", texto)
        self.assertNotIn("duda interna", texto)
        self.assertNotIn("Pregunta solo para el especialista", texto)

        self.assertEqual(skill.indice_criterios(),
                         ["PRB-01 · Criterio confirmado", "PRB-02 · Criterio por confirmar"])
        self.assertRegex(skill.version_completa, r"^medio\.prueba@1#[0-9a-f]{12}$")

    def test_reporta_todos_los_errores_y_no_carga_la_skill(self):
        self.escribir("medios/mala.md", textwrap.dedent("""\
            ---
            id: medio.mala
            tipo: medio
            titulo: Mala
            version: uno
            estado: publicado
            ---

            ## Criterios de valoración

            ### XX · Sin número
            ### MAL-01 · Sin estado ni fuente
            Texto.
            """))
        repo = SkillFileRepository(self.dir)
        errores = "\n".join(repo.errores())
        for esperado in ("'version' debe ser un número", "estado 'publicado' no válido",
                         "necesita 'medio'", "necesita la sección 'Cómo leerlo'",
                         "el título debe ser 'ID-01 · Nombre'",
                         "MAL-01: estado '' no válido", "MAL-01: falta la fuente"):
            self.assertIn(esperado, errores)
        self.assertEqual(repo.todas(), [])

    def test_ids_de_criterio_unicos_entre_archivos(self):
        self.escribir("medios/prueba.md", SKILL_MINIMA)
        self.escribir("medios/otra.md", SKILL_MINIMA.replace("medio.prueba", "medio.otra")
                      .replace("medio: prueba", "medio: otra"))
        repo = SkillFileRepository(self.dir)
        self.assertEqual(len(repo.todas()), 1)
        self.assertTrue(any("PRB-01 ya definido" in e for e in repo.errores()))

    def test_skill_inactiva_no_se_entrega(self):
        self.escribir("medios/prueba.md", SKILL_MINIMA.replace("estado: activo", "estado: inactivo", 1))
        self.assertIsNone(SkillFileRepository(self.dir).para_medio("prueba"))

    def test_relee_el_archivo_cuando_cambia(self):
        ruta = self.escribir("medios/prueba.md", SKILL_MINIMA)
        repo = SkillFileRepository(self.dir)
        self.assertEqual(repo.para_medio("prueba").version, 1)

        ruta.write_text(SKILL_MINIMA.replace("version: 1", "version: 2"), encoding="utf-8")
        futuro = time.time() + 5
        os.utime(ruta, (futuro, futuro))   # garantiza un mtime distinto
        self.assertEqual(repo.para_medio("prueba").version, 2)


if __name__ == "__main__":
    unittest.main()
