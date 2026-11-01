"""Textos con el formato que usa EMAPA en la conciliación y la resolución.

Las partes fijas (normas citadas, frases de cierre, presentación de recursos)
se arman aquí, sin LLM, para que no varíen ni se inventen números de
resolución. La IA solo redacta el sustento técnico (la frase "AL HABERSE
VERIFICADO QUE ...") y, en un FUNDADO, el borrador del procedimiento de
refacturación, que el analista completa con los importes.

Formatos de referencia entregados por EMAPA (noviembre 2026):
- Propuesta/acta de conciliación: "EN PRESENCIA DEL RECLAMANTE SR. ..., CON DNI
  N° ... Y EN APLICACIÓN DE LO DISPUESTO EN EL REGLAMENTO GENERAL DE RECLAMOS ...
  058-2023-SUNASS-CD, SE LLEVÓ A CABO LA AUDIENCIA DE CONCILIACIÓN, CONCLUYENDO
  EN LO SIGUIENTE: DECLARAR ... EL PRESENTE RECLAMO CORRESPONDIENTE AL MES ...".
- Resolución (Se resuelve): "EN VIRTUD DE LO EXPUESTO, Y EN APLICACIÓN DE LA
  RCD Nº 066 2006-SUNASS-CD, ... SE DECLARA ... EL PRESENTE RECLAMO." +
  PROCEDIMIENTO DE REFACTURACIÓN (si es FUNDADO) + PRESENTACIÓN DE RECURSOS.
"""

from __future__ import annotations

import re

from app.src.core.model.conciliacion import Conciliacion
from app.src.core.model.informe_atencion import InformeAtencion

REGLAMENTO_RECLAMOS = (
    "REGLAMENTO GENERAL DE RECLAMOS DE USUARIOS DE LOS SERVICIOS DE SANEAMIENTO, "
    "APROBADO MEDIANTE RESOLUCIÓN DE CONSEJO DIRECTIVO N.º 058-2023-SUNASS-CD"
)

SE_RESUELVE_BASE = (
    "EN VIRTUD DE LO EXPUESTO, Y EN APLICACIÓN DE LA RESOLUCIÓN DE CONSEJO DIRECTIVO "
    "Nº 066-2006-SUNASS-CD, LA RESOLUCIÓN DE CONSEJO DIRECTIVO Nº 015-2023-SUNASS-CD Y "
    "RESOLUCIÓN DE CONSEJO DIRECTIVO Nº 058-2023-SUNASS-CD, TEXTO ÚNICO ORDENADO DEL "
    "REGLAMENTO DE CALIDAD DE LA PRESTACIÓN DE LOS SERVICIOS DE SANEAMIENTO, SE "
    "DECLARA {veredicto} EL PRESENTE RECLAMO."
)

PRESENTACION_RECURSOS = (
    "PRESENTACIÓN DE RECURSOS:\n"
    "EN CASO DE QUE USUARIO SE ENCUENTRE INCONFORME CON LA PRESENTE RESOLUCIÓN, "
    "DISPONDRÁ DE 15 DÍAS HÁBILES PARA PRESENTAR SU RECURSO DE APELACIÓN O "
    "RECONSIDERACIÓN, EL MISMO QUE PUEDE SER PRESENTADO DE FORMA PRESENCIAL EN "
    "NUESTRA OFICINA UBICADO EN JIRÓN MANUELA MOREY N°110 - TARAPOTO."
)

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SETIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
_NUM_MES = {m: i + 1 for i, m in enumerate(MESES)} | {"SEPTIEMBRE": 9}

# Postura del reclamante y puntos de acuerdo/desacuerdo según el resultado
# (mismos textos que el Formato N° 4 ya usa por defecto para la aceptación).
DATOS_POR_RESULTADO = {
    "acepta": ("ACEPTAR LA PROPUESTA DE LA EPS", "LO PROPUESTO POR LA EPS", "NINGUNO"),
    "no_acepta": ("NO ACEPTA LA PROPUESTA DE LA EPS", "NINGUNO", "LO PROPUESTO POR LA EPS"),
    "no_asistio": ("NO ASISTIÓ A LA AUDIENCIA DE CONCILIACIÓN", "NINGUNO", "NINGUNO"),
}


def _mayus(texto: str | None) -> str:
    return re.sub(r"\s+", " ", (texto or "").strip()).upper()


def periodos_texto(meses_reclamados: str | None) -> str:
    """'SETIEMBRE-2026' -> 'AL MES SETIEMBRE 2026';
    'JULIO-2026, AGOSTO-2026' -> 'A LOS MESES JULIO 2026 Y AGOSTO 2026'."""
    encontrados = []
    for nombre, anio in re.findall(r"([A-Za-zÁÉÍÓÚñÑ]+)[\s\-/]+(\d{4})", meses_reclamados or ""):
        nombre = nombre.upper()
        if nombre in _NUM_MES and f"{nombre} {anio}" not in encontrados:
            encontrados.append(f"{nombre} {anio}")
    if not encontrados:
        return "AL MES RECLAMADO"
    if len(encontrados) == 1:
        return f"AL MES {encontrados[0]}"
    return f"A LOS MESES {', '.join(encontrados[:-1])} Y {encontrados[-1]}"


def articulos_citados(informe: InformeAtencion) -> list[str]:
    """Numerales de los artículos que sustentan la decisión: los marcados como
    aplicables en los problemas seleccionados de la fundamentación; si no hay,
    los que cite el párrafo de fundamentación ('Art. 88.4', 'artículo 88')."""
    numerales: list[str] = []
    for bloque in informe.bloques:
        for p in bloque.problemas:
            if not p.seleccionado:
                continue
            for a in p.articulos or []:
                if a.get("aplica") is False:
                    continue
                n = str(a.get("numeral") or a.get("article") or "").strip()
                if n and n not in numerales:
                    numerales.append(n)
    if not numerales and informe.fundamentacion_normativa:
        for n in re.findall(r"art[íi]culo\s+(\d+(?:\.\d+)*)|art\.\s*(\d+(?:\.\d+)*)",
                            informe.fundamentacion_normativa, re.I):
            valor = n[0] or n[1]
            if valor and valor not in numerales:
                numerales.append(valor)
    return numerales


def _nombre_reclamante(informe: InformeAtencion) -> str:
    r = informe.datos_reclamo
    return _mayus((r.reclamante or r.propietario) if r else None) or "[NOMBRE DEL RECLAMANTE]"


def _dni(informe: InformeAtencion) -> str:
    r = informe.datos_reclamo
    return _mayus(r.dni if r else None) or "[DNI]"


def resultado_conciliacion(c: Conciliacion | None) -> str:
    """'acepta' | 'no_acepta' | 'no_asistio' | 'pendiente' (campos de SYSCO:
    ASISTIÓ y ¿SUBSISTE EL RECLAMO?)."""
    if c is None or c.asistio is None:
        return "pendiente"
    if c.asistio is False:
        return "no_asistio"
    if c.subsiste is None:
        return "pendiente"
    return "no_acepta" if c.subsiste else "acepta"


def propuesta_conciliacion(informe: InformeAtencion, sustento: str, c: Conciliacion | None) -> str:
    """Texto completo de la propuesta / acta de conciliación con el formato de
    EMAPA. El cierre depende del resultado de la audiencia; mientras esté
    pendiente se redacta como propuesta de la EPS."""
    veredicto = _mayus(informe.veredicto) or "[FUNDADO/INFUNDADO]"
    reclamante, dni = _nombre_reclamante(informe), _dni(informe)
    periodo = periodos_texto(informe.datos_reclamo.meses_reclamados if informe.datos_reclamo else None)
    resultado = resultado_conciliacion(c)
    via = " VÍA TELEFÓNICA" if c is not None and c.por_telefono else ""

    if resultado == "no_asistio":
        apertura = (
            f"ANTE LA INASISTENCIA DEL RECLAMANTE SR(A). {reclamante}, CON DNI N° {dni}, "
            f"Y EN APLICACIÓN DE LO DISPUESTO EN EL {REGLAMENTO_RECLAMOS}, SE DEJA CONSTANCIA "
            "DE LA AUDIENCIA DE CONCILIACIÓN PROGRAMADA, EN LA QUE LA EPS PROPONE LO SIGUIENTE: "
            f"DECLARAR {veredicto} EL PRESENTE RECLAMO CORRESPONDIENTE {periodo}."
        )
    elif resultado in ("acepta", "no_acepta"):
        apertura = (
            f"EN PRESENCIA DEL RECLAMANTE SR(A). {reclamante}, CON DNI N° {dni} Y EN APLICACIÓN "
            f"DE LO DISPUESTO EN EL {REGLAMENTO_RECLAMOS}, SE LLEVÓ A CABO LA AUDIENCIA DE "
            f"CONCILIACIÓN{via}, CONCLUYENDO EN LO SIGUIENTE: DECLARAR {veredicto} EL PRESENTE "
            f"RECLAMO CORRESPONDIENTE {periodo}."
        )
    else:
        apertura = (
            f"EN APLICACIÓN DE LO DISPUESTO EN EL {REGLAMENTO_RECLAMOS}, LA EPS PROPONE AL "
            f"RECLAMANTE SR(A). {reclamante}, CON DNI N° {dni}, LO SIGUIENTE: DECLARAR "
            f"{veredicto} EL PRESENTE RECLAMO CORRESPONDIENTE {periodo}."
        )

    articulos = articulos_citados(informe)
    norma = (f"ADEMÁS, SE ENCUENTRA ACORDE A LO DESCRITO EN LA NORMATIVA, SEÑALADA EN EL "
             f"ART. {', '.join(articulos)}, " if articulos else "ADEMÁS, SE ENCUENTRA ACORDE A LA NORMATIVA VIGENTE, ")
    sustento = _mayus(sustento).rstrip(".;,") or "[SUSTENTO TÉCNICO DE LA DECISIÓN]"
    if not sustento.startswith("AL HABERSE VERIFICADO"):
        sustento = f"AL HABERSE VERIFICADO QUE {sustento}"
    desarrollo = (f"{sustento}; {norma}POR LO TANTO, EL PROCEDIMIENTO CONTINUARÁ CONFORME A "
                  "LAS DISPOSICIONES NORMATIVAS VIGENTES.")

    cierre = {
        "acepta": (f"EL USUARIO ACEPTA LA PROPUESTA DE CONCILIACIÓN PLANTEADA POR LA EPS RESPECTO A "
                   f"DECLARAR {veredicto} EL PRESENTE RECLAMO. EL PROCEDIMIENTO CONTINÚA CONFORME A LEY."),
        "no_acepta": (f"EL USUARIO NO ACEPTA LA PROPUESTA DE CONCILIACIÓN PLANTEADA POR LA EPS RESPECTO A "
                      f"DECLARAR {veredicto} EL PRESENTE RECLAMO, POR LO QUE EL RECLAMO SUBSISTE. EL "
                      "PROCEDIMIENTO CONTINÚA CONFORME A LEY."),
        "no_asistio": ("AL NO HABER ASISTIDO EL RECLAMANTE A LA AUDIENCIA DE CONCILIACIÓN, EL RECLAMO "
                       "SUBSISTE. EL PROCEDIMIENTO CONTINÚA CONFORME A LEY."),
        "pendiente": "",
    }[resultado]
    return "\n\n".join(p for p in (apertura, f"{desarrollo} {cierre}".strip()) if p)


def parrafo_conciliacion_informe(informe: InformeAtencion) -> str | None:
    """Párrafo que actualiza el informe de atención con el resultado de la
    audiencia. None mientras no haya resultado registrado."""
    c = informe.propuesta_conciliacion
    resultado = resultado_conciliacion(c)
    if resultado == "pendiente":
        return None
    veredicto = (informe.veredicto or "").upper() or "[FUNDADO/INFUNDADO]"
    fecha = f" el {c.fecha_audiencia}" if c and c.fecha_audiencia else ""
    via = " por vía telefónica" if c and c.por_telefono else ""
    if resultado == "acepta":
        return (f"Resultado de la conciliación: realizada la audiencia de conciliación{fecha}{via}, "
                f"el usuario aceptó la propuesta de la EPS de declarar {veredicto} el reclamo; "
                "en consecuencia, el reclamo no subsiste.")
    if resultado == "no_acepta":
        return (f"Resultado de la conciliación: realizada la audiencia de conciliación{fecha}{via}, "
                f"el usuario no aceptó la propuesta de la EPS de declarar {veredicto} el reclamo, "
                "por lo que el reclamo subsiste y se resolverá conforme a lo determinado en el presente informe.")
    return (f"Resultado de la conciliación: el usuario no asistió a la audiencia de conciliación "
            f"programada{fecha}, por lo que el reclamo subsiste y se resolverá conforme a lo "
            "determinado en el presente informe.")


def tabla_lecturas_reclamadas(informe: InformeAtencion) -> list[list[str]]:
    """Filas (mes, lect. anterior, lect. última, consumo) de los meses
    reclamados según la tarjeta de lecturas, como punto de partida del cuadro
    de nivelación que el analista corrige."""
    from app.src.application.services.informe.evidencias import construir_serie
    filas = []
    for s in construir_serie(informe):
        if not s["reclamado"]:
            continue
        def n(v):
            return "" if v is None else (str(int(v)) if float(v).is_integer() else str(v))
        filas.append([f"{MESES[s['mes'] - 1]}-{s['anio']}", n(s["lectura_anterior"]),
                      n(s["lectura_actual"]), n(s["consumo"])])
    return filas


def se_resuelve(informe: InformeAtencion, procedimiento: list[str] | None = None) -> str:
    """Parte resolutiva con el formato de EMAPA. En un FUNDADO agrega el
    PROCEDIMIENTO DE REFACTURACIÓN (borrador: los importes los completa el
    analista) y el cuadro de nivelación de lecturas de los meses reclamados."""
    veredicto = (informe.veredicto or "").upper()
    partes = [SE_RESUELVE_BASE.format(veredicto=veredicto or "[FUNDADO/INFUNDADO]")]
    if veredicto == "FUNDADO":
        pasos = [p.strip().rstrip(".") + "." for p in (procedimiento or []) if p and p.strip()]
        if not pasos:
            pasos = ["[DETALLAR LA REFACTURACIÓN: IMPORTE FACTURADO, REBAJA A FAVOR DEL USUARIO, "
                     "IMPORTE A CANCELAR Y DIFERENCIA A ANULAR]."]
        filas = tabla_lecturas_reclamadas(informe)
        if filas:
            pasos.append("ÁREA DE FACTURACIÓN Y MEDICIÓN, NIVELAR LECTURAS, TOMAR EN CUENTA Y CORREGIR "
                         "LECTURAS, SEGÚN CUADRO SIGUIENTE.")
        lineas = ["PROCEDIMIENTO DE REFACTURACIÓN:"] + [f"{i}. {p}" for i, p in enumerate(pasos, 1)]
        if filas:
            lineas.append("MES | LECT. ANTERIOR | LECT. ÚLTIMA | CONS. FACTURAR M3")
            lineas += [" | ".join(f) for f in filas]
            lineas.append("[VERIFICAR LAS LECTURAS Y EL CONSUMO A FACTURAR DEL CUADRO]")
        partes.append("\n".join(lineas))
    partes.append(PRESENTACION_RECURSOS)
    return "\n\n".join(partes)
