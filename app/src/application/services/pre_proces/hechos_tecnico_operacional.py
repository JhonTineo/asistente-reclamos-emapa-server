"""Hechos del informe técnico operacional (continuidad, interrupciones, VPA).

Los criterios VPA-01, VPA-02, INT-01 y OPE-01 necesitan saber, del sector del
predio: si el servicio es continuo o restringido, si hubo interrupciones en el
periodo reclamado y si existe una válvula de purga de aire (VPA) operativa.

- **Formulario:** las casillas ya vienen resueltas en el texto extraído
  ("Existencia de VPA en la zona: No hay VPA."); se leen con reglas.
- **Narrativo** (y lo que el formulario no trae, como el horario): un
  extractor con LLM devuelve cada campo con la cita literal del informe. Si la
  cita no aparece en el texto, el campo queda "no determinado": el modelo no
  puede afirmar algo que el informe no dice.

Los hechos resultantes son constataciones con un ``valor`` estructurado
(``{"continuo": false}``, ``{"existe": false}``...) que el dictamen y su
verificador pueden comprobar sin interpretar prosa.
"""

import json
import logging
import re
import unicodedata

from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("services.hechos_tecnico_operacional")

FUENTE = "tecnico_operacional.texto_extraido"
CAMPOS = ("horario", "interrupciones", "vpa_existe", "vpa_operativa")

# Casillas del formulario, tal como las escribe pre_tecnico_operacional.
_CASILLAS = {
    "interrupciones": (
        r"En el periodo reclamado hubo interrupciones en el abastecimiento:\s*([^.\n]+)",
        {"si": True, "no": False},
    ),
    "vpa_existe": (
        r"Existencia de VPA en la zona:\s*([^.\n]+)",
        {"si hay vpa": True, "no hay vpa": False},
    ),
    "vpa_operativa": (
        r"Estado de la VPA:\s*([^.\n]+)",
        {"operativa": True, "inoperativa": False},
    ),
}


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_acentos.casefold().split())


def _campo(valor=None, cita: str | None = None, **extra) -> dict:
    return {"valor": valor, "cita": cita, **extra}


# ---------------------------------------------------------------------- #
# Formulario: reglas
# ---------------------------------------------------------------------- #
def campos_desde_formulario(texto: str) -> dict[str, dict]:
    """Lee las casillas del formulario. Una casilla "No determinada" (sin X
    legible o con varias marcas) queda con valor None."""
    campos: dict[str, dict] = {}
    for nombre, (patron, opciones) in _CASILLAS.items():
        encontrado = re.search(patron, texto or "", re.IGNORECASE)
        if not encontrado:
            continue
        respuesta = _normalizar(encontrado.group(1))
        valor = next((v for k, v in opciones.items() if respuesta == k), None)
        campos[nombre] = _campo(valor, encontrado.group(0).strip())
    return campos


# ---------------------------------------------------------------------- #
# Narrativo (y horario): extractor con LLM y citas literales
# ---------------------------------------------------------------------- #
# Las instrucciones del extractor están en skills/pasos/extraccion_operacional.md.


def _parsear_json(texto: str) -> dict:
    texto = (texto or "").strip()
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        encontrado = re.search(r"\{.*\}", texto, re.DOTALL)
        data = json.loads(encontrado.group()) if encontrado else {}
    return data if isinstance(data, dict) else {}


def campos_con_llm(texto: str, llm_router, modelo_id: str,
                   codreclamo: str | None = None) -> dict[str, dict]:
    """Extrae los campos con el LLM y descarta los que no tienen una cita
    literal del informe (el dato quedaría sin respaldo)."""
    respuesta = constructor_contexto.llamar(
        "extraccion_operacional", llm_router, modelo_id,
        entrada=f"INFORME:\n{texto}", codreclamo=codreclamo,
    )
    data = _parsear_json(respuesta)
    texto_norm = _normalizar(texto)
    campos: dict[str, dict] = {}
    for nombre in CAMPOS:
        crudo = data.get(nombre)
        if not isinstance(crudo, dict):
            continue
        cita = (crudo.get("cita") or "").strip() or None
        if crudo.get("valor") is not None and (not cita or _normalizar(cita) not in texto_norm):
            logger.warning("[OPERACIONAL] Se descarta '%s': su cita no está en el informe", nombre)
            continue
        campo = _campo(crudo.get("valor"), cita)
        if nombre == "horario":
            continuo = crudo.get("continuo")
            campo["continuo"] = continuo if isinstance(continuo, bool) and cita else None
            if not isinstance(campo["valor"], str):
                campo["valor"] = None
        elif not isinstance(campo["valor"], bool):
            campo["valor"] = None
        campos[nombre] = campo
    return campos


# ---------------------------------------------------------------------- #
# Hechos
# ---------------------------------------------------------------------- #
def _hecho(tipo: str, detalle: str, valor: dict, cita: str | None) -> ProblemaNormado:
    return ProblemaNormado(
        tipo=tipo, detalle=detalle, fuente=FUENTE, texto_original=cita,
        clase="constatacion", valor=valor,
    )


def construir_hechos(campos: dict[str, dict]) -> list[ProblemaNormado]:
    hechos: list[ProblemaNormado] = []
    prefijo = "El informe técnico operacional"

    horario = campos.get("horario") or {}
    continuo = horario.get("continuo")
    texto_horario = f" ({horario['valor']})" if horario.get("valor") else ""
    if continuo is True:
        detalle = f"{prefijo} indica que el sector tiene servicio continuo las 24 horas{texto_horario}."
    elif continuo is False:
        detalle = (f"{prefijo} indica que el sector tiene servicio restringido a ciertas "
                   f"horas{texto_horario}, es decir, servicio discontinuo.")
    else:
        detalle = f"{prefijo} no permite determinar si el servicio del sector es continuo."
    hechos.append(_hecho("horarioAbastecimiento", detalle,
                         {"continuo": continuo, "horario": horario.get("valor")}, horario.get("cita")))

    interrupciones = (campos.get("interrupciones") or {}).get("valor")
    detalle = {
        True: f"{prefijo} indica que hubo interrupciones del abastecimiento en el periodo reclamado.",
        False: f"{prefijo} indica que no hubo interrupciones del abastecimiento en el periodo reclamado.",
    }.get(interrupciones, f"{prefijo} no permite determinar si hubo interrupciones en el periodo reclamado.")
    hechos.append(_hecho("interrupcionesPeriodo", detalle, {"hubo": interrupciones},
                         (campos.get("interrupciones") or {}).get("cita")))

    existe = (campos.get("vpa_existe") or {}).get("valor")
    operativa = (campos.get("vpa_operativa") or {}).get("valor") if existe is not False else None
    if existe is False:
        detalle = f"{prefijo} indica que no existe válvula de purga de aire (VPA) en la zona."
    elif existe is True and operativa is True:
        detalle = f"{prefijo} indica que existe una válvula de purga de aire (VPA) operativa en la zona."
    elif existe is True and operativa is False:
        detalle = f"{prefijo} indica que la válvula de purga de aire (VPA) de la zona está inoperativa."
    elif existe is True:
        detalle = (f"{prefijo} indica que existe una válvula de purga de aire (VPA) en la zona, "
                   "sin precisar si está operativa.")
    else:
        detalle = f"{prefijo} no permite determinar si existe una válvula de purga de aire (VPA) en la zona."
    cita_vpa = " / ".join(c for c in ((campos.get("vpa_existe") or {}).get("cita"),
                                      (campos.get("vpa_operativa") or {}).get("cita")) if c) or None
    hechos.append(_hecho("vpaZona", detalle, {"existe": existe, "operativa": operativa}, cita_vpa))
    return hechos


def extraer_hechos(datos: dict, llm_router=None, modelo_id: str | None = None,
                   codreclamo: str | None = None) -> list[ProblemaNormado]:
    """Hechos del informe a partir de ``asdict(InformeTecnicoOperacional)``.
    Sin LLM, solo se usan las casillas del formulario. Nunca interrumpe el
    análisis: ante un error, devuelve los hechos que se pudieron determinar."""
    texto = datos.get("texto_extraido") or ""
    campos: dict[str, dict] = {}
    if llm_router is not None and texto:
        try:
            campos.update(campos_con_llm(texto, llm_router, modelo_id, codreclamo))
        except Exception:  # noqa: BLE001
            logger.exception("[OPERACIONAL] Falló el extractor; se usan solo las casillas")
    # Las casillas del formulario son deterministas: prevalecen sobre el LLM.
    if datos.get("formato") == "formulario":
        campos.update({k: v for k, v in campos_desde_formulario(texto).items() if v["valor"] is not None
                       or k not in campos})
    return construir_hechos(campos)
