"""Criterios de especialista: entidad de dominio.

Son la lógica de negocio con la que se clasifica cada objetivo de investigación
en `procede_correccion`, `sin_correccion` o `no_evaluable` (los consume el
ConclusionAgent al evaluar los objetivos contra los hallazgos).

Se administran HOY EN CÓDIGO (editando CRITERIOS_DEFECTO), pero se consumen a
través de `obtener_criterios()`: ese es el único punto a cambiar para leerlos
mañana de una base de datos (persistencia), sin tocar el resto. Cada criterio se
puede agregar, editar o desactivar (activo=False) de forma independiente.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CriterioEvaluacion:
    """Un criterio concreto que sustenta clasificar un objetivo en `resultado`."""
    resultado: str       # "procede_correccion" | "sin_correccion" | "no_evaluable"
    texto: str           # el caso, en lenguaje natural
    activo: bool = True  # permite desactivar un criterio sin borrarlo


# Definición breve de cada resultado (encabeza su lista de criterios en el prompt).
RESULTADO_DEFINICION: dict[str, str] = {
    "procede_correccion": "corresponde corregir/refacturar la facturación a favor del usuario",
    "sin_correccion": "la facturación fue correcta y NO corresponde corregir nada",
    "no_evaluable": "los hallazgos no permiten evaluar el objetivo",
}

# Orden en que se presentan los resultados en el prompt.
_ORDEN = ("procede_correccion", "sin_correccion", "no_evaluable")


CRITERIOS_DEFECTO: list[CriterioEvaluacion] = [
    CriterioEvaluacion(
        "procede_correccion",
        "un error atribuible a la EMPRESA: medidor defectuoso, error de medición, "
        "lectura mal registrada o cobro indebido",
    ),
    CriterioEvaluacion(
        "procede_correccion",
        "FUGA NO VISIBLE ya reparada (Art. 88.3, rama 2): la inspección confirmó que "
        "la fuga era NO VISIBLE (oculta, no detectable a simple vista) Y que el usuario "
        "la reparó dentro del plazo de 15 días. Corresponde refacturar los meses "
        "afectados por el promedio histórico. "
        "IMPORTANTE: solo aplica si los hallazgos indican explícitamente 'no visible'",
    ),
    CriterioEvaluacion(
        "sin_correccion",
        "el medidor y las lecturas son correctos, no se halló fuga ni error de medición",
    ),
    CriterioEvaluacion(
        "sin_correccion",
        "FUGA VISIBLE (Art. 88.3, rama 1): la inspección halló una fuga VISIBLE "
        "(detectable a simple vista, p. ej. 'fuga visible en inodoro', 'pérdida de agua "
        "visible en tubería'). La empresa factura por diferencia de lecturas "
        "INDEPENDIENTEMENTE de si ya fue reparada. La visibilidad de la fuga, no la "
        "reparación, es lo que determina este caso",
    ),
    CriterioEvaluacion(
        "sin_correccion",
        "FUGA NO VISIBLE que NO fue reparada (Art. 88.3, rama 3): la inspección "
        "reveló fuga no visible pero el usuario no la reparó dentro del plazo de 15 días "
        "o la fuga persiste. La empresa factura por diferencia de lecturas",
    ),
    CriterioEvaluacion(
        "no_evaluable",
        "el medio del objetivo aún no fue analizado o sus datos no alcanzan para decidir",
    ),
]


def obtener_criterios() -> list[CriterioEvaluacion]:
    """Fuente de los criterios. Hoy devuelve la lista en código; es el único punto
    a cambiar para leerlos de una BD en el futuro."""
    return CRITERIOS_DEFECTO


def render_criterios(criterios: list[CriterioEvaluacion]) -> str:
    """Renderiza los criterios ACTIVOS agrupados por resultado, para el prompt."""
    por_resultado: dict[str, list[str]] = {r: [] for r in _ORDEN}
    for c in criterios:
        if c.activo and c.resultado in por_resultado:
            por_resultado[c.resultado].append(c.texto)

    lineas: list[str] = []
    for r in _ORDEN:
        lineas.append(f'- "{r}": {RESULTADO_DEFINICION[r]}. Aplica cuando:')
        for texto in por_resultado[r]:
            lineas.append(f"    · {texto}")
    return "\n".join(lineas)
