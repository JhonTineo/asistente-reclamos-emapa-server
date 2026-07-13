"""Construye el texto en lenguaje natural del informe de atención a partir de
sus bloques (uno por medio probatorio), con la estructura del informe real de
EMAPA: metadatos -> introducción -> hallazgos numerados -> conclusión.
"""

from app.src.core.model.informe_atencion import InformeAtencion, BloqueMedio

INTRO = (
    "Mediante el presente, me dirijo a Usted, para informarle que, en atención "
    "al reclamo presentado para el suministro N.º {suministro}, se ha realizado "
    "el procedimiento establecido en la normativa, el mismo que nos conlleva al "
    "siguiente resultado:"
)

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _fecha_es(fecha) -> str:
    if not fecha:
        return ""
    return f"{fecha.day:02d} de {MESES_ES[fecha.month - 1]} del {fecha.year}"


def _render_bloque(indice: int, bloque: BloqueMedio) -> str:
    lineas = [f"{indice}. {bloque.medio_nombre}: {bloque.resumen}"]

    if bloque.tiene_problemas:
        lineas.append("   Se detalla a continuación:")
        for p in bloque.problemas:
            responsable = p.responsable or "no_determinable"
            base = f" ({p.base_legal})" if p.base_legal else ""
            accion = p.accion or "Sin acción determinada."
            lineas.append(
                f"   - {p.detalle}\n"
                f"     Acción: {accion}\n"
                f"     Responsabilidad: {responsable}{base}"
            )

    return "\n".join(lineas)


def construir_texto_informe(informe: InformeAtencion) -> str:
    fecha = _fecha_es(informe.fecha)

    cabecera = [
        f"INFORME N.º {informe.numero}",
        "",
        f"A         : {informe.destinatario or ''}",
        f"ASUNTO    : {informe.asunto}",
        f"REF.      : RECLAMO {informe.reclamo} - SUMINISTRO N.º {informe.suministro}",
        f"FECHA     : {fecha}",
        "-" * 90,
        "",
        INTRO.format(suministro=informe.suministro),
        "",
    ]

    cuerpo = [
        _render_bloque(i, bloque)
        for i, bloque in enumerate(informe.bloques, start=1)
    ]

    partes = ["\n".join(cabecera), "\n\n".join(cuerpo)]

    if informe.conclusion:
        partes.append("\nEn consecuencia, " + informe.conclusion)

    return "\n".join(partes).strip()
