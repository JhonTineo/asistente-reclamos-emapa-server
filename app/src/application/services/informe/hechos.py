"""Registro de hechos del caso: asigna a cada problema detectado un ID estable.

Un hecho es la unidad mínima de evidencia del informe ("H-tl-02": el consumo de
12/2025 fue 48 m³, 3 veces el promedio). Los artefactos generados citarán esos
IDs, lo que permite verificar que cada afirmación tiene respaldo y saber qué
partes del informe dependen de un hecho cuando este cambia.

Reglas de los IDs:
- Formato ``H-<prefijo del medio>-<número de 2 dígitos>``.
- Si un medio se vuelve a analizar y un problema se repite (mismo tipo, detalle
  y fuente), conserva su ID: el hecho es el mismo.
- La numeración por medio nunca retrocede (``InformeAtencion.secuencia_hechos``),
  así un ID de un hecho ya reemplazado no vuelve a usarse para otro distinto.
"""

from app.src.core.model.informe_atencion import BloqueMedio, InformeAtencion, ProblemaNormado

PREFIJOS_MEDIO = {
    "tarjeta_lectura": "tl",
    "record_facturacion": "rf",
    "corte_reapertura": "cr",
    "saldo_detalle": "sd",
    "saldo_actual": "sa",
    "inspeccion_interna": "ii",
    "inspeccion_externa": "ie",
    "tecnico_operacional": "to",
}


def _prefijo(medio_id: str) -> str:
    return PREFIJOS_MEDIO.get(medio_id, medio_id)


def _clave(problema: ProblemaNormado) -> tuple[str, str, str, str]:
    return (problema.clase, problema.tipo, problema.detalle.strip(), (problema.fuente or "").strip())


def _siguiente_id(informe: InformeAtencion, medio_id: str) -> str:
    numero = informe.secuencia_hechos.get(medio_id, 0) + 1
    informe.secuencia_hechos[medio_id] = numero
    return f"H-{_prefijo(medio_id)}-{numero:02d}"


def _registrar_id_existente(informe: InformeAtencion, medio_id: str, hecho_id: str) -> None:
    """Mantiene la secuencia por encima de los IDs que ya existen (p.ej. si se
    cargó un bloque con IDs de otra corrida)."""
    try:
        numero = int(hecho_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return
    if numero > informe.secuencia_hechos.get(medio_id, 0):
        informe.secuencia_hechos[medio_id] = numero


def asignar_ids_bloque(
    informe: InformeAtencion,
    bloque: BloqueMedio,
    anterior: BloqueMedio | None = None,
) -> None:
    """Asigna IDs a los hechos de ``bloque`` (problemas y constataciones, que
    comparten la numeración del medio). Reutiliza el ID de ``anterior`` (el
    bloque del mismo medio que se reemplaza) cuando el hecho es el mismo; si
    no, toma el siguiente número del medio."""
    previos: dict[tuple[str, str, str, str], str] = {}
    if anterior is not None:
        for p in anterior.hechos:
            if p.id:
                previos.setdefault(_clave(p), p.id)

    usados: set[str] = set()
    for problema in bloque.hechos:
        if problema.id and problema.id not in usados:
            _registrar_id_existente(informe, bloque.medio_id, problema.id)
            usados.add(problema.id)
            continue
        reutilizable = previos.get(_clave(problema))
        if reutilizable and reutilizable not in usados:
            problema.id = reutilizable
        else:
            problema.id = _siguiente_id(informe, bloque.medio_id)
        usados.add(problema.id)


def asegurar_ids_hechos(informe: InformeAtencion) -> None:
    """Garantiza que todo problema del informe tenga ID (red de seguridad para
    bloques que no pasaron por ``registrar_bloque``)."""
    for bloque in informe.bloques:
        if any(not p.id for p in bloque.hechos):
            asignar_ids_bloque(informe, bloque)
