"""Capas de contexto: los bloques con que se arma cada llamada al LLM.

Hay un único catálogo de capas con un orden fijo. Cada paso del workflow elige
cuáles usa (ver ``especificaciones.py``), pero el orden nunca cambia:

    system  1. instrucciones   rol_base
            2. conocimiento    skill, normativa
    user    3. caso            reclamo, hechos, datos_medio, textos_previos
            4. tarea           tarea

Lo estable va arriba y lo que cambia en cada llamada va abajo: así el
proveedor puede reutilizar el prefijo en caché y la tarea queda al final, que
es lo que el modelo atiende mejor.

Este módulo solo convierte datos en texto; no decide qué entra (eso es de las
especificaciones) ni llama al LLM (eso es del constructor).
"""

import json
import re
from dataclasses import dataclass

from app.src.core.model.informe_atencion import InformeAtencion, ProblemaNormado
from app.src.core.model.skill import Skill

INSTRUCCIONES = "instrucciones"
CONOCIMIENTO = "conocimiento"
CASO = "caso"
TAREA = "tarea"

# nombre de la capa -> familia. El orden de este diccionario ES el orden en que
# las capas aparecen en el contexto.
CATALOGO: dict[str, str] = {
    "rol_base": INSTRUCCIONES,
    "skill": CONOCIMIENTO,
    # Instrucciones del paso que dependen del caso (p.ej. el veredicto ya
    # decidido o la fórmula de cierre): las arma el paso en código.
    "instrucciones": INSTRUCCIONES,
    "normativa": CONOCIMIENTO,
    "reclamo": CASO,
    "objetivos": CASO,
    "hechos": CASO,
    "datos_medio": CASO,
    # Datos del caso que el paso ya preparó en su formato propio (la lista de
    # hallazgos a evaluar, el documento a extraer…).
    "entrada": CASO,
    "textos_previos": CASO,
    "tarea": TAREA,
}
FAMILIAS_SYSTEM = (INSTRUCCIONES, CONOCIMIENTO)

MARCA_RECORTE = "\n[… recortado para respetar el presupuesto de contexto]"

# Identificadores internos de hechos ([H-tl-01], [H-caso-02]…). Sirven para que
# el modelo cite hechos en campos JSON; nunca deben quedar en un texto redactado.
_ID_HECHO = re.compile(r"\s*\[H-[A-Za-z]+-\d+\]")


def quitar_identificadores(texto: str) -> str:
    return _ID_HECHO.sub("", texto) if texto else texto


@dataclass
class Capa:
    nombre: str
    contenido: str
    recortada: bool = False

    @property
    def familia(self) -> str:
        return CATALOGO[self.nombre]

    @property
    def va_en_system(self) -> bool:
        return self.familia in FAMILIAS_SYSTEM

    @property
    def caracteres(self) -> int:
        return len(self.contenido)

    def recortar(self, caracteres_a_quitar: int) -> int:
        """Acorta la capa en al menos ``caracteres_a_quitar`` y devuelve cuántos
        caracteres quitó realmente."""
        antes = len(self.contenido)
        conservar = max(0, antes - caracteres_a_quitar - len(MARCA_RECORTE))
        self.contenido = self.contenido[:conservar].rstrip() + MARCA_RECORTE
        self.recortada = True
        return max(0, antes - len(self.contenido))


# ---------------------------------------------------------------------- #
# Instrucciones y conocimiento
# ---------------------------------------------------------------------- #
def render_rol_base(skills_base: list[Skill], secciones: tuple[str, ...] | None = None) -> str:
    """``secciones`` limita el rol base a esas secciones (p.ej. sin «Cómo
    escribir» en los pasos que no redactan); None = todas."""
    return "\n\n".join(
        s.render(secciones or s.secciones_para_modelo(), titulo=False) for s in skills_base
    ).strip()


def render_skills(skills_y_secciones: list[tuple[Skill, list[str]]],
                  criterios_excluidos: frozenset[str] | set[str] = frozenset()) -> str:
    partes = [skill.render(secciones, excluir_criterios=criterios_excluidos)
              for skill, secciones in skills_y_secciones]
    # Una skill que solo aportó su título (sin secciones con contenido) no entra.
    return "\n\n".join(p for p in partes if p.strip() and "\n" in p.strip())


def render_normativa(hechos: list[ProblemaNormado]) -> str:
    """Artículos ya recuperados para los hechos (sin consultar Qdrant de nuevo),
    sin repetir el mismo artículo y numeral."""
    vistos: set[tuple] = set()
    lineas: list[str] = []
    for hecho in hechos:
        articulos = hecho.articulos or []
        # Si la fundamentación ya marcó qué artículos aplican, solo entran esos:
        # los demás son ruido recuperado por similitud (y ocupan miles de tokens).
        if any("aplica" in a for a in articulos):
            articulos = [a for a in articulos if a.get("aplica")]
        for articulo in articulos:
            clave = (articulo.get("article"), articulo.get("numeral"))
            if clave in vistos or not articulo.get("texto"):
                continue
            vistos.add(clave)
            numeral = f", numeral {clave[1]}" if clave[1] not in (None, "") else ""
            lineas.append(f"### Artículo {clave[0]}{numeral}\n{articulo['texto'].strip()}")
    if not lineas:
        return ""
    return "## Normativa recuperada para los hechos del caso\n\n" + "\n\n".join(lineas)


# ---------------------------------------------------------------------- #
# Caso
# ---------------------------------------------------------------------- #
def render_reclamo(informe: InformeAtencion | None, clasificacion: str | None = None) -> str:
    reclamo = informe.datos_reclamo if informe else None
    campos = [
        ("Clasificación", (reclamo.clasificacion_reclamo if reclamo else None) or clasificacion),
        ("Tipo", reclamo.tipo_reclamo if reclamo else None),
        ("Meses reclamados", reclamo.meses_reclamados if reclamo else None),
        ("Fecha de recepción", reclamo.fecha_recepcion if reclamo else None),
        ("Motivo", reclamo.motivo_reclamo if reclamo else None),
    ]
    lineas = [f"- {nombre}: {valor}" for nombre, valor in campos if valor]
    return "## Reclamo\n" + "\n".join(lineas) if lineas else ""


def _linea_hecho(hecho: ProblemaNormado) -> str:
    prefijo = f"[{hecho.id}] " if hecho.id else ""
    return f"- {prefijo}{hecho.detalle}"


def render_hechos(hechos: list[ProblemaNormado], titulo: str | None = None) -> str:
    """Separa los hallazgos (anomalías detectadas por reglas) de los hechos
    verificados (constataciones), que el modelo no debe contradecir."""
    problemas = [h for h in hechos if h.clase not in ("constatacion", "alegacion")]
    constataciones = [h for h in hechos if h.clase == "constatacion"]
    alegaciones = [h for h in hechos if h.clase == "alegacion"]
    partes: list[str] = []
    if titulo:
        partes.append(f"## {titulo}")
    if alegaciones:
        partes.append("ALEGACIONES del usuario (NO verificadas: la evidencia debe "
                      "confirmarlas o descartarlas):\n"
                      + "\n".join(_linea_hecho(h) for h in alegaciones))
    if problemas:
        partes.append("Hallazgos detectados por las reglas del sistema:\n"
                      + "\n".join(_linea_hecho(h) for h in problemas))
    if constataciones:
        partes.append("HECHOS VERIFICADOS por el sistema (son exactos; úsalos con sus "
                      "cifras y no los contradigas):\n"
                      + "\n".join(_linea_hecho(h) for h in constataciones))
    return "\n\n".join(partes) if (problemas or constataciones or alegaciones) else ""


def render_hechos_por_medio(informe: InformeAtencion,
                            hechos_caso: list[ProblemaNormado] | None = None) -> str:
    partes = [render_hechos(hechos_caso or [], "Hechos del caso (reclamo completo)")]
    partes += [
        render_hechos(bloque.hechos, f"Hechos de {bloque.medio_nombre}")
        for bloque in informe.bloques if bloque.hechos
    ]
    return "\n\n".join(p for p in partes if p)


def render_objetivos(informe: InformeAtencion | None) -> str:
    if not informe or not informe.objetivos:
        return ""
    lineas = [
        f"- {o.descripcion}" + (f" [medio: {o.medio}]" if o.medio else "")
        for o in informe.objetivos
    ]
    return ("## Preguntas de la investigación (guía; no deciden el veredicto)\n"
            + "\n".join(lineas))


def _vacio(valor) -> bool:
    return valor is None or (isinstance(valor, (str, list, dict, tuple)) and not valor)


def depurar_datos(datos: dict, hechos: list[ProblemaNormado]) -> dict:
    """Quita de los datos crudos lo que solo agrega ruido al modelo:
    - campos vacíos (``"errorConsumo": []``), que el modelo tiende a "describir"
      como "no se registraron consumos atípicos…";
    - elementos que ya entran como hechos con su ID (mismo texto), para no
      repetir la misma evidencia dos veces."""
    ya_en_hechos = {h.detalle.strip() for h in hechos if h.detalle}
    depurados: dict = {}
    for clave, valor in datos.items():
        if isinstance(valor, list):
            valor = [v for v in valor if not (isinstance(v, str) and v.strip() in ya_en_hechos)]
        elif isinstance(valor, str) and valor.strip() in ya_en_hechos:
            continue
        if not _vacio(valor):
            depurados[clave] = valor
    return depurados


def render_datos_medio(medio_nombre: str, datos: dict) -> str:
    if not datos:
        return ""
    texto = json.dumps(datos, ensure_ascii=False, indent=2, default=str)
    return f"## Datos obtenidos del medio: {medio_nombre}\n{texto}"


def render_textos_previos(informe: InformeAtencion, excluir_medio: str | None = None) -> str:
    lineas = [
        f"- {bloque.medio_nombre}: {bloque.resumen.strip()}"
        for bloque in informe.bloques
        if bloque.resumen and bloque.medio_id != excluir_medio
    ]
    return "## Resúmenes de los medios analizados\n" + "\n".join(lineas) if lineas else ""
