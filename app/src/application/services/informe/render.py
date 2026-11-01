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
    # El detalle problema-por-problema (acción/base legal) no se renderiza en
    # el texto: el resumen del medio ya lo narra en prosa, y la conclusión
    # cierra con el veredicto. Esos datos siguen disponibles estructurados en
    # bloque.problemas (respuesta de la API) para quien los necesite aparte.
    return f"{indice}. {bloque.medio_nombre}: {bloque.resumen}"


def construir_texto_informe(informe: InformeAtencion) -> str:
    # Los informes ya existentes en SYSCO pueden haber sido redactados a mano o
    # por una ejecución anterior de la IA. Se conserva el documento original en
    # vez de intentar reconstruirlo con bloques que no existen en esta sesión.
    if informe.informe_texto_original:
        return informe.informe_texto_original

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

    # La fundamentación normativa es el punto numerado que sigue a los resúmenes
    # de los medios y precede a la conclusión (como el punto normativo del
    # informe real que cita el artículo/numeral aplicable).
    if informe.fundamentacion_normativa:
        cuerpo.append(f"{len(informe.bloques) + 1}. {informe.fundamentacion_normativa}")

    partes = ["\n".join(cabecera), "\n\n".join(cuerpo)]

    if informe.conclusion:
        # Sin título: la conclusión es un párrafo que arranca con "En
        # consecuencia, ..." a continuación de los hallazgos, como el informe real.
        partes.append("\n" + informe.conclusion)

    return "\n".join(partes).strip()
