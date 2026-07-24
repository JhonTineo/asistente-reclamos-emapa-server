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
        "una FUGA NO VISIBLE YA REPARADA: el consumo elevado retornó al promedio en "
        "un mes posterior, lo que obliga a refacturar los meses afectados por el "
        "promedio histórico",
    ),
    CriterioEvaluacion(
        "sin_correccion",
        "el medidor y las lecturas son correctos y no se halló fuga",
    ),
    CriterioEvaluacion(
        "sin_correccion",
        "el problema es responsabilidad del cliente y persiste (fuga visible o no "
        "reparada), por lo que se factura por diferencia de lecturas",
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
