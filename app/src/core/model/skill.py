"""Skill: conocimiento del oficio para analizar un medio o un tipo de reclamo.

Una skill viene de un archivo Markdown (ver ``app/src/skills/README.md``). Aquí
está su forma en memoria y cómo se convierte en texto para el modelo. Las
partes pensadas solo para personas (las preguntas abiertas y las dudas
pendientes de cada criterio) nunca se incluyen en ese texto.
"""

import unicodedata
from dataclasses import dataclass, field

ESTADOS_SKILL = ("activo", "borrador", "inactivo")
ESTADOS_CRITERIO = ("activo", "por_confirmar", "inactivo")
# decisivo: por sí solo puede decidir el veredicto; indicio: apoya, no decide.
FUERZAS_CRITERIO = ("decisivo", "indicio")
TIPOS_SKILL = ("base", "medio", "tipo_reclamo", "paso")

SECCION_ROL = "Rol"
SECCION_INSTRUCCIONES = "Instrucciones"
SECCION_LECTURA = "Cómo leerlo"
SECCION_CRITERIOS = "Criterios de valoración"
SECCION_METODO = "Método de decisión"
SECCION_PRUEBAS = "Qué debe probar la empresa"
SECCION_QUE_ES = "Qué es"
# Secciones que existen para el especialista y el equipo, no para el modelo.
SECCIONES_SOLO_PERSONAS = ("Preguntas abiertas", "Notas")


def normalizar_titulo(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_acentos.casefold().split())


@dataclass(frozen=True)
class Criterio:
    id: str                  # "VPA-01": único entre todas las skills
    nombre: str
    estado: str              # activo | por_confirmar | inactivo
    fuente: str              # artículo(s) y/o quién lo definió
    cuerpo: str              # explicación (por qué importa, cuándo aplica...)
    pendiente: str | None = None   # duda para el especialista (no va al modelo)
    fuerza: str = "indicio"  # decisivo | indicio
    # Condiciones para que el criterio pueda aplicar: alternativas (basta una)
    # de la forma "tipoDeHecho" o "tipoDeHecho.campo=valor". Las comprueba el
    # código, no el modelo (que no ve los valores de los hechos): el dictamen
    # descarta el criterio antes de la llamada si ningún hecho las cumple, y el
    # verificador exige que algún hecho citado cumpla una de ellas.
    requiere: tuple[str, ...] = ()

    @property
    def vigente(self) -> bool:
        return self.estado != "inactivo"

    def render(self) -> str:
        marca = " (por confirmar con el especialista)" if self.estado == "por_confirmar" else ""
        return (f"### {self.id} · {self.nombre}{marca}\nFuente: {self.fuente}\n"
                f"Fuerza: {self.fuerza}\n\n{self.cuerpo}")


@dataclass(frozen=True)
class Skill:
    id: str                  # "medio.tarjeta_lectura"
    tipo: str                # medio | tipo_reclamo
    titulo: str
    version: int
    estado: str              # activo | borrador | inactivo
    ruta: str
    hash: str                # huella del archivo: con qué versión exacta se decidió
    secciones: dict[str, str] = field(default_factory=dict)   # título -> contenido
    criterios: tuple[Criterio, ...] = ()
    medio: str | None = None
    paso: str | None = None                 # solo en skills de paso ("objetivos", …)
    codigos_tipo_reclamo: tuple[str, ...] = ()
    clasificaciones: tuple[str, ...] = ()
    actualizado: str | None = None
    validado_por: str | None = None

    @property
    def version_completa(self) -> str:
        """Identificador para guardar junto a cada informe: "medio.x@1#ab12cd"."""
        return f"{self.id}@{self.version}#{self.hash}"

    def seccion(self, titulo: str) -> str | None:
        buscado = normalizar_titulo(titulo)
        for nombre, contenido in self.secciones.items():
            if normalizar_titulo(nombre) == buscado:
                return contenido
        return None

    def criterios_vigentes(self) -> list[Criterio]:
        return [c for c in self.criterios if c.vigente]

    def render_criterios(self, excluir: frozenset[str] | set[str] = frozenset()) -> str:
        return "\n\n".join(c.render() for c in self.criterios_vigentes() if c.id not in excluir)

    def indice_criterios(self) -> list[str]:
        """Una línea por criterio vigente, para dar contexto sin el detalle."""
        return [f"{c.id} · {c.nombre}" for c in self.criterios_vigentes()]

    def secciones_para_modelo(self) -> list[str]:
        """Todas las secciones, en el orden del archivo, salvo las que son solo
        para personas."""
        excluidas = {normalizar_titulo(s) for s in SECCIONES_SOLO_PERSONAS}
        return [s for s in self.secciones if normalizar_titulo(s) not in excluidas]

    def render(self, secciones: list[str] | tuple[str, ...], titulo: bool = True,
               excluir_criterios: frozenset[str] | set[str] = frozenset()) -> str:
        """Texto para el modelo con las secciones pedidas, en ese orden. La
        sección de criterios se reconstruye solo con los criterios vigentes,
        sin los de ``excluir_criterios`` (los que el código ya descartó)."""
        partes = [f"# {self.titulo}"] if titulo else []
        excluidas = {normalizar_titulo(s) for s in SECCIONES_SOLO_PERSONAS}
        for nombre in secciones:
            if normalizar_titulo(nombre) in excluidas:
                continue
            if normalizar_titulo(nombre) == normalizar_titulo(SECCION_CRITERIOS):
                contenido = self.render_criterios(excluir_criterios)
            else:
                contenido = self.seccion(nombre)
            if contenido:
                partes.append(f"## {nombre}\n{contenido}")
        return "\n\n".join(partes)
