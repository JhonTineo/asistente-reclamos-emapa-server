"""Artefactos del informe: los textos que Yumi genera o que el analista edita.

Cada artefacto tiene un tipo estable (``resumen:<medio_id>``, ``fundamentacion``,
``conclusion``, ``conciliacion``, ``resolucion``). La persistencia guarda una
nueva versión cada vez que su contenido cambia, sin sobrescribir la anterior.

El origen de un texto (``generado``, ``analista`` o ``sysco``) se registra con
``marcar_origen`` en el momento en que ocurre la edición o la recuperación. La
marca guarda una firma del contenido: si después un agente regenera el texto,
la firma deja de coincidir y el origen vuelve a ser ``generado`` sin que el
agente tenga que saber nada de esto.
"""

import json
from dataclasses import asdict

from app.src.core.model.informe_atencion import InformeAtencion

ORIGEN_GENERADO = "generado"
ORIGEN_ANALISTA = "analista"
ORIGEN_SYSCO = "sysco"


def tipo_resumen(medio_id: str) -> str:
    return f"resumen:{medio_id}"


def artefactos_actuales(informe: InformeAtencion) -> dict[str, tuple[str, dict | None]]:
    """tipo -> (texto, datos estructurados opcionales) de los artefactos que
    existen ahora en el informe. Los textos vacíos no cuentan como artefacto."""
    actuales: dict[str, tuple[str, dict | None]] = {}
    for bloque in informe.bloques:
        if bloque.resumen:
            actuales[tipo_resumen(bloque.medio_id)] = (bloque.resumen, None)
    if informe.fundamentacion_normativa:
        actuales["fundamentacion"] = (informe.fundamentacion_normativa, None)
    if informe.conclusion:
        actuales["conclusion"] = (informe.conclusion, None)
    if informe.propuesta_conciliacion is not None:
        datos = asdict(informe.propuesta_conciliacion)
        actuales["conciliacion"] = (datos.get("propuesta_empresa") or "", datos)
    if informe.resolucion:
        actuales["resolucion"] = (informe.resolucion, None)
    return actuales


def firma(texto: str, datos: dict | None) -> str:
    return json.dumps([texto, datos], ensure_ascii=False, sort_keys=True, default=str)


def marcar_origen(informe: InformeAtencion, tipo: str, origen: str) -> None:
    """Registra el origen del contenido ACTUAL del artefacto ``tipo``."""
    actual = artefactos_actuales(informe).get(tipo)
    if actual is None:
        informe.marcas_origen.pop(tipo, None)
        return
    informe.marcas_origen[tipo] = (origen, firma(*actual))


def origen_de(informe: InformeAtencion, tipo: str, texto: str, datos: dict | None) -> str:
    marca = informe.marcas_origen.get(tipo)
    if marca and marca[1] == firma(texto, datos):
        return marca[0]
    return ORIGEN_GENERADO
