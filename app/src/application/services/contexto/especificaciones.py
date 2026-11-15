"""Qué capas de contexto recibe cada paso del workflow.

Para cambiar lo que ve un paso, o agregar un paso nuevo, se edita este archivo:
el paso en sí solo pide su contexto por nombre (``constructor.construir("...")``).

Cada especificación define:
- ``capas``: subconjunto del catálogo de ``capas.py`` (el orden lo fija el
  catálogo, no esta lista);
- de qué skills sale la capa ``skill`` y con qué secciones;
- qué hechos entran (los del medio que se analiza o todos los del caso);
- el presupuesto de tokens y qué capas se recortan primero si no cabe
  (rol_base, skill, hechos y tarea nunca se recortan);
- la tarea: la instrucción final, armada con los datos de la llamada.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.src.core.model.skill import (
    SECCION_CRITERIOS, SECCION_LECTURA, SECCION_METODO, SECCION_PRUEBAS, SECCION_QUE_ES,
    SECCION_ROL,
)

CAPAS_PROTEGIDAS = frozenset({"rol_base", "skill", "hechos", "tarea", "instrucciones", "entrada"})

# Rol base para los pasos que razonan sobre los hechos pero no redactan texto
# del informe: quién es Yumi y cómo tratar los datos, sin las reglas de estilo.
SECCIONES_BASE_SIN_REDACCION = (SECCION_ROL, "Reglas sobre los datos")


@dataclass(frozen=True)
class ContextSpec:
    paso: str
    capas: tuple[str, ...]
    tarea: Callable[[dict], str]
    skill_paso: bool = False                # incluir skills/pasos/<paso>.md § Instrucciones
    secciones_medio: tuple[str, ...] = ()   # secciones de la skill del medio
    secciones_tipo: tuple[str, ...] = ()    # secciones de la skill del tipo de reclamo
    medios_del_caso: bool = False           # skill de CADA medio analizado (dictamen)
    hechos: str = "del_medio"               # "del_medio" | "todos"
    presupuesto_tokens: int = 6000
    recortar_primero: tuple[str, ...] = ()
    salida: str = "texto"                   # "texto" | "json"
    # Secciones del rol base que recibe el paso (None = todas). Los pasos que
    # no redactan texto para el informe no llevan «Cómo escribir».
    secciones_base: tuple[str, ...] | None = None
    # Tope de tokens de la respuesta (None = el del adaptador). El dictamen
    # devuelve un JSON largo y necesita más que el techo general.
    max_tokens_respuesta: int | None = None

    def __post_init__(self):
        protegidas = CAPAS_PROTEGIDAS & set(self.recortar_primero)
        if protegidas:
            raise ValueError(f"{self.paso}: no se pueden recortar {sorted(protegidas)}")


# ---------------------------------------------------------------------- #
# Tareas
# ---------------------------------------------------------------------- #
def _tarea_resumen_medio(datos: dict) -> str:
    partes = [
        f"Redacta el resumen del medio probatorio «{datos.get('medio_nombre', '')}» "
        f"para un reclamo de: {datos.get('clasificacion') or 'no especificado'}.",
        "Redacta UN SOLO párrafo breve, normalmente de 2 a 4 oraciones; no añadas "
        "relleno para llegar a ese número. Describe lo documentado sin atribuir "
        "causas ni decidir el veredicto.",
    ]
    if datos.get("enfoque"):
        partes.append(
            f"La investigación de este medio busca responder: {datos['enfoque']} "
            "Si los datos lo permiten, incluye los hechos que responden esa pregunta; "
            "respóndela con hechos, no con una valoración (no escribas, por ejemplo, "
            "que algo «justifica» o «explica» el consumo). Si los datos NO lo permiten, "
            "no lo inventes, pero tampoco dejes el resumen en una disculpa: igual "
            "describe brevemente los hechos que SÍ muestran los datos."
        )
    partes.append(
        "No enumeres lo que no ocurrió (\"no se registraron…\", \"tampoco hubo…\") "
        "salvo que responda directamente a la pregunta de la investigación."
    )
    partes.append(
        "No cierres con una valoración ni una conclusión como \"lo que sugiere…\", "
        "\"lo que podría indicar…\" o \"no revelan anomalías que justifiquen…\": "
        "valorar la evidencia corresponde al dictamen."
    )
    if any(h.clase == "constatacion" for h in datos.get("hechos") or []):
        partes.append(
            "Si hay un hecho verificado sobre el mes reclamado, empieza el resumen por "
            "él. No afirmes que falta información de un mes que aparece en los hechos "
            "verificados."
        )
    partes.append("Responde ÚNICAMENTE con el párrafo, sin encabezados ni listas.")
    return "## Tarea\n" + "\n".join(partes)


def _tarea_dictamen(datos: dict) -> str:
    partes = [
        "## Tarea",
        "Evalúa el caso siguiendo el método de decisión. Para CADA criterio de "
        "valoración listado arriba, decide si aplica a este caso según sus "
        "condiciones («Favorece al usuario cuando…», «Pesa poco cuando…»):",
        "- \"aplica\": sus condiciones se cumplen. Cita en \"hechos\" al menos un "
        "identificador de hecho que lo sustente e indica en \"favorece\" a quién "
        "favorece: \"usuario\", \"empresa\" o \"revision\" (si el criterio pide "
        "marcar el caso para revisión).",
        "- \"no_aplica\": los hechos muestran que sus condiciones no se cumplen.",
        "- \"no_determinable\": falta el hecho que permitiría saberlo.",
        "Un criterio describe una situación; «aplica» significa que ESA situación "
        "ocurre en el caso. Si el criterio trata de un defecto (p.ej. una lectura no "
        "válida) y los hechos muestran que no lo hay, es \"no_aplica\".",
        "Sé breve: en los criterios \"no_aplica\" la \"explicacion\" es una sola frase "
        "corta; en los demás, una o dos oraciones.",
    ]
    if datos.get("criterios_descartados"):
        partes.append(
            "El sistema ya comprobó que estos criterios NO aplican, porque ningún hecho "
            "del caso cumple su condición. No los incluyas en \"factores\" y tenlo en "
            "cuenta al evaluar los demás: "
            + "; ".join(datos["criterios_descartados"]) + "."
        )
    partes += [
        "Toda prueba faltante debe citarse en algún criterio. Toda alegación del "
        "usuario debe citarse en el criterio que la examina (aunque no aplique) o, si "
        "ningún criterio la cubre, explicarse en \"alegaciones\". En \"criterio\" van "
        "solo IDs de criterios (como VPA-01); los IDs de hechos (como H-caso-01) van "
        "en \"hechos\". No uses hechos ni criterios que no estén en este mensaje, y no "
        "decidas por el primer factor que encuentres: un hecho puede quedar sin efecto "
        "por otro más directo; explícalo en \"explicacion\".",
        "Responde ÚNICAMENTE con un objeto JSON con esta forma:",
        '{"factores": [{"criterio": "VPA-01", "aplica": "aplica|no_aplica|no_determinable", '
        '"hechos": ["H-to-01"], "favorece": "usuario|empresa|revision|ninguno", '
        '"explicacion": "una o dos oraciones"}], '
        '"alegaciones": [{"hecho": "H-caso-01", "explicacion": "cómo la confirman o descartan los hechos"}], '
        '"conflictos": ["..."], "pruebas_faltantes": ["..."], '
        '"veredicto_propuesto": "FUNDADO|INFUNDADO|REVISION", '
        '"razonamiento": "un párrafo con el razonamiento completo"}',
    ]
    if datos.get("critica"):
        partes.append(
            "Tu respuesta anterior tuvo estos problemas; corrígelos y responde de "
            "nuevo con el JSON completo:\n" + "\n".join(f"- {c}" for c in datos["critica"])
        )
    return "\n".join(partes)


# ---------------------------------------------------------------------- #
# Especificaciones
# ---------------------------------------------------------------------- #
ESPECIFICACIONES: dict[str, ContextSpec] = {
    "resumen_medio": ContextSpec(
        paso="resumen_medio",
        capas=("rol_base", "skill", "reclamo", "hechos", "datos_medio", "tarea"),
        tarea=_tarea_resumen_medio,
        secciones_medio=(SECCION_LECTURA,),
        hechos="del_medio",
        presupuesto_tokens=6000,
        recortar_primero=("datos_medio",),
    ),
    # Paso de dictamen (pasos/dictamen.py): evalúa los criterios con todos los hechos.
    "dictamen": ContextSpec(
        paso="dictamen",
        capas=("rol_base", "skill", "normativa", "reclamo", "objetivos", "hechos",
               "textos_previos", "tarea"),
        tarea=_tarea_dictamen,
        secciones_tipo=(SECCION_QUE_ES, SECCION_PRUEBAS, SECCION_METODO, SECCION_CRITERIOS),
        secciones_medio=(SECCION_CRITERIOS,),
        medios_del_caso=True,
        hechos="todos",
        presupuesto_tokens=12000,
        # La normativa se recorta primero: los criterios de las skills ya
        # resumen y citan los artículos; los resúmenes son cortos y útiles.
        recortar_primero=("normativa", "textos_previos", "objetivos"),
        salida="json",
        secciones_base=SECCIONES_BASE_SIN_REDACCION,
        # Un factor por criterio (más de diez en un caso típico) + razonamiento:
        # con el techo general de 1500 la respuesta se cortaba a medio JSON.
        max_tokens_respuesta=4000,
    ),
}


def _sin_tarea(_datos: dict) -> str:
    return ""


def _paso(paso: str, *, rol_base: bool = True, salida: str = "texto",
          presupuesto: int = 12000,
          secciones_base: tuple[str, ...] | None = None) -> ContextSpec:
    """Paso cuyo contexto es: rol base (opcional) + su skill de paso + sus
    instrucciones dependientes del caso + la entrada que prepara en código. La
    tarea va al final de la entrada (la escribe el propio paso)."""
    capas = (("rol_base",) if rol_base else ()) + ("skill", "instrucciones", "entrada")
    return ContextSpec(paso=paso, capas=capas, tarea=_sin_tarea, skill_paso=True,
                       presupuesto_tokens=presupuesto, salida=salida,
                       secciones_base=secciones_base)


# Pasos que preparan sus propios datos. El rol base solo acompaña a quien lo
# necesita:
# - completo, a los pasos que REDACTAN texto del informe;
# - sin las reglas de estilo, a los que razonan sobre los hechos (objetivos);
# - ninguno, a los que solo eligen índices o clasifican (selección,
#   aplicabilidad, interpretación, evaluación) y a los extractores, que copian
#   texto literal: ahí las reglas de redacción son ruido y sus ejemplos
#   terminaban copiados en la respuesta.
for _spec in (
    _paso("objetivos", salida="json", secciones_base=SECCIONES_BASE_SIN_REDACCION),
    _paso("fundamentacion_seleccion", rol_base=False, salida="json"),
    _paso("fundamentacion_interpretacion", rol_base=False, salida="json"),
    _paso("fundamentacion_aplicabilidad", rol_base=False, salida="json"),
    _paso("fundamentacion_parrafo"),
    _paso("evaluacion_objetivos", rol_base=False, salida="json"),
    _paso("conclusion_redaccion"),
    _paso("conciliacion"),
    _paso("resolucion"),
    _paso("extraccion_sysco", rol_base=False, salida="json"),
    _paso("extraccion_operacional", rol_base=False, salida="json"),
):
    ESPECIFICACIONES[_spec.paso] = _spec


def obtener_especificacion(paso: str) -> ContextSpec:
    try:
        return ESPECIFICACIONES[paso]
    except KeyError:
        raise KeyError(f"No hay especificación de contexto para el paso '{paso}'") from None
