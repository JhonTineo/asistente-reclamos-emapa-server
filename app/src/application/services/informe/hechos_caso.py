"""Hechos del caso completo: no salen de un medio, sino del reclamo en conjunto.

- **Alegaciones** del usuario, tomadas del motivo (p.ej. "no cuento con el
  servicio de 24 horas"). Son ``clase="alegacion"``: NO están verificadas; son
  lo que la evidencia debe confirmar o descartar. Sin ellas, el dictamen no
  sabría que una causa alegada quedó sin examinar.
- **Pruebas faltantes:** medios que el RGR (Anexo 3) exige para el tipo de
  reclamo y que no se analizaron. Alimentan el criterio PRU-01 (Art. 12.1).

Se calculan cada vez a partir del informe (son deterministas) y llevan IDs
``H-caso-NN``, estables mientras el informe no cambie.
"""

import re
import unicodedata

from app.src.core.model.informe_atencion import InformeAtencion, ProblemaNormado

FUENTE_MOTIVO = "reclamo.motivo"

# Expresiones del motivo que alegan falta o discontinuidad del servicio.
_DISCONTINUIDAD = [
    r"\b24\s*HORAS\b",
    r"\bSIN\s+(EL\s+)?(AGUA|SERVICIO)\b",
    r"\bNO\s+(HAY|LLEGA|TENGO|TENEMOS|CUENTO\s+CON|CONTAMOS\s+CON)\s+(EL\s+)?(AGUA|SERVICIO)\b",
    r"\bCORT(E|ES|AN|ARON)\s+(DE(L)?\s+)?(AGUA|SERVICIO)\b",
    r"\bDESABASTEC",
    r"\bPOCAS\s+HORAS\b",
    r"\bAIRE\b",
    # "horario" solo cuenta si va con una queja ("horario restringido", "solo
    # llega en horario de…"); pedir inspecciones "en el horario de
    # abastecimiento" NO es alegar discontinuidad (caso 252629).
    r"\bHORARIO\s+(RESTRINGIDO|REDUCIDO|LIMITADO)\b",
    r"\bSOLO\s+(LLEGA|HAY|TENGO|TENEMOS)\s+(AGUA\s+)?(EN|POR|DE)\b",
]

# Medios que el RGR (Anexo 3, B.1.1) exige en reclamos de consumo medido.
# "condicion" indica cuándo es exigible.
_PRUEBAS_CONSUMO_MEDIDO = [
    ("inspeccion_externa", "siempre",
     "la inspección externa, que el RGR (Anexo 3) exige en todo reclamo por "
     "consumo medido para detectar fugas que incrementen el consumo"),
    # Exigible SIEMPRE: el Anexo 3 pide en todo reclamo por consumo medido el
    # informe del área de control operacional con el reporte de continuidad e
    # interrupciones del mes reclamado; solo el plano y las válvulas de purga
    # de aire dependen de que haya discontinuidad. Antes se exigía solo si el
    # usuario alegaba falta de agua (corregido 2026-11-20).
    ("tecnico_operacional", "siempre",
     "el informe del área de control operacional, que el RGR (Anexo 3, B.1.1) exige en "
     "todo reclamo por consumo medido para acreditar que el medidor refleja el consumo "
     "efectuado (reporte de continuidad e interrupciones del mes reclamado y, si hay "
     "discontinuidad, la ubicación y operatividad de las válvulas de purga de aire)"),
]


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def _fragmento(motivo: str, inicio: int, fin: int, margen: int = 60) -> str:
    a = max(0, inicio - margen)
    b = min(len(motivo), fin + margen)
    texto = " ".join(motivo[a:b].split())
    return ("…" if a > 0 else "") + texto + ("…" if b < len(motivo) else "")


def alegacion_discontinuidad(motivo: str | None) -> ProblemaNormado | None:
    if not motivo:
        return None
    normalizado = _sin_acentos(motivo).upper()
    for patron in _DISCONTINUIDAD:
        encontrado = re.search(patron, normalizado)
        if encontrado:
            cita = _fragmento(motivo, encontrado.start(), encontrado.end())
            return ProblemaNormado(
                tipo="alegacionDiscontinuidad",
                detalle=("El usuario alega falta o discontinuidad del servicio de agua: "
                         f"«{cita}». No está verificado."),
                fuente=FUENTE_MOTIVO, texto_original=motivo.strip(),
                clase="alegacion", valor={"verificado": False},
            )
    return None


def _hay_discontinuidad(informe: InformeAtencion, alegada: bool) -> bool:
    """La discontinuidad hace exigible el informe operacional: basta con que el
    usuario la alegue o que algún hecho la muestre (servicio restringido,
    interrupciones o una inspección interna sin abastecimiento)."""
    if alegada:
        return True
    for bloque in informe.bloques:
        for hecho in bloque.hechos:
            valor = hecho.valor or {}
            if hecho.tipo == "horarioAbastecimiento" and valor.get("continuo") is False:
                return True
            if hecho.tipo == "interrupcionesPeriodo" and valor.get("hubo") is True:
                return True
        if bloque.medio_id == "inspeccion_interna" and "sin abastecimiento" in (
            str((bloque.entidad or {}).get("estadoabas") or "").lower()
        ):
            return True
    return False


def _es_consumo_medido(informe: InformeAtencion) -> bool:
    return (informe.clasificacion or "").strip().upper().startswith("A1")


def hechos_del_caso(informe: InformeAtencion) -> list[ProblemaNormado]:
    hechos: list[ProblemaNormado] = []
    alegacion = alegacion_discontinuidad(informe.motivo)
    if alegacion:
        hechos.append(alegacion)

    if _es_consumo_medido(informe):
        analizados = {b.medio_id for b in informe.bloques}
        discontinuidad = _hay_discontinuidad(informe, alegacion is not None)
        for medio_id, condicion, descripcion in _PRUEBAS_CONSUMO_MEDIDO:
            exigible = condicion == "siempre" or (condicion == "discontinuidad" and discontinuidad)
            if exigible and medio_id not in analizados:
                hechos.append(ProblemaNormado(
                    tipo="pruebaFaltante",
                    detalle=f"No se cuenta con {descripcion}.",
                    fuente="caso.medios_analizados",
                    valor={"medio": medio_id, "condicion": condicion},
                ))

    for numero, hecho in enumerate(hechos, start=1):
        hecho.id = f"H-caso-{numero:02d}"
    return hechos
