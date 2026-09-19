"""Servicio de aplicación para el informe de atención automatizado: la
búsqueda del reclamo + creación de metadatos, propia del flujo de un solo
disparo (POST /reclamos/informe-atencion). Se mantiene separada de la
búsqueda manual (GET /reclamos/reclamo/...) porque acá cualquier fallo debe
cortar todo el proceso (HTTPException) en vez de devolverse como un mensaje
en el cuerpo (200 con `error`), pensado para que el usuario lo vea en pantalla.
"""

import json
import logging
import re
import unicodedata

from fastapi import HTTPException

from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.application.ports.provider_port import MensajeLLM
from app.src.infrastructure.adapters.http_client import EmapaSinDatosError
from app.src.application.services.informe.informe_store import informe_store, ReclamoEnAtencionError
from app.src.application.services.investigacion.reclamo_service import campo_reclamo, codigo_inspeccion
from app.src.application.services.informe.medios_probatorios import obtener_medios_probatorios
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.reclamo import Reclamo
from app.src.core.model.informe_atencion import InformeAtencion
from app.src.core.model.conciliacion import Conciliacion

logger = logging.getLogger("services.informe_service")

_VALORES_PENDIENTES = {"", "PENDIENTE"}
_VEREDICTOS = {"FUNDADO", "INFUNDADO"}
_PATRON_DECLARACION = re.compile(
    r"\b(?:SE\s+)?DECLARA(?:R)?\s+(INFUNDADO|FUNDADO)\b",
    re.IGNORECASE,
)
_PATRON_VEREDICTO = re.compile(r"\b(INFUNDADO|FUNDADO)\b", re.IGNORECASE)


def _detalle_sysco(datos: dict | None) -> dict:
    """Devuelve ``datos.data`` como diccionario, tolerando la variante lista."""
    data = datos.get("data") if isinstance(datos, dict) else None
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {}


def _ultimo_dict(valor) -> dict:
    if isinstance(valor, dict):
        return valor
    if isinstance(valor, list):
        return next((item for item in reversed(valor) if isinstance(item, dict)), {})
    return {}


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _sin_acentos(texto: str) -> str:
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caracter) != "Mn"
    )


def _normalizar_comparacion(texto: str) -> str:
    return " ".join(_sin_acentos(texto).casefold().split())


def _extraer_veredicto(texto: str) -> str | None:
    """Extrae una decisión explícita; nunca la deduce por el contenido."""
    declaraciones = [m.upper() for m in _PATRON_DECLARACION.findall(texto)]
    if declaraciones:
        unicos = set(declaraciones)
        return declaraciones[-1] if len(unicos) == 1 else None

    menciones = {m.upper() for m in _PATRON_VEREDICTO.findall(texto)}
    return next(iter(menciones)) if len(menciones) == 1 else None


def _extraer_formato_generado(
    texto: str,
    medios_probatorios: list[dict[str, str]],
) -> dict | None:
    """Separa el formato propio y recupera sus resúmenes por medio.

    La cabecera no se valida porque SYSCO persiste únicamente el cuerpo y el
    frontend agrega la cabecera fija al renderizarlo.

    Todo bloque numerado cuyo título coincide con un medio es su resumen. El
    último bloque anterior a la conclusión que no corresponde a un medio es la
    fundamentación; si todos corresponden a medios, no hay fundamentación.
    """
    match_conclusion = re.search(
        r"(?ims)^\s*(En\s+consecuencia,.*)\s*$",
        texto,
    )
    if not match_conclusion:
        return None

    conclusion = match_conclusion.group(1).strip()
    veredicto = _extraer_veredicto(conclusion)
    if not veredicto:
        return None

    cuerpo_anterior = texto[:match_conclusion.start()]
    bloques = list(re.finditer(
        r"(?ms)^\s*\d+\.\s+(.+?)(?=\n\s*\n|\Z)",
        cuerpo_anterior,
    ))
    # Los nombres históricos del renderer presentan diferencias menores con el
    # catálogo (Record/Récord, Lectura/Lecturas, Corte/Cortes). Para comparar se
    # quitan acentos y una "s" plural final de cada palabra.
    def clave_medio(valor: str) -> str:
        return " ".join(
            palabra[:-1] if palabra.endswith("s") else palabra
            for palabra in _normalizar_comparacion(valor).split()
        )

    ids_por_nombre = {
        clave_medio(medio["nombre"]): medio["id"]
        for medio in medios_probatorios
    }
    resumenes: dict[str, str] = {}
    fundamentacion = None
    for match in bloques:
        contenido = match.group(1).strip()
        titulo, separador, resumen = contenido.partition(":")
        medio_id = ids_por_nombre.get(clave_medio(titulo)) if separador else None
        if medio_id:
            resumenes[medio_id] = resumen.strip()
        else:
            # Por contrato del informe IA, si existe estará inmediatamente
            # antes de la conclusión. Conservar el último no-medio implementa
            # esa regla sin confundir el último resumen con fundamentación.
            fundamentacion = contenido

    # Sin al menos un título de medio conocido no se considera el formato
    # estructurado; el texto libre se delega al extractor LLM.
    if not resumenes:
        return None

    return {
        "fundamentacion": fundamentacion,
        "conclusion": conclusion,
        "veredicto": veredicto,
        "resumenes": resumenes,
    }


def _parsear_json_extraccion(respuesta: str) -> dict:
    texto = (respuesta or "").strip()
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if not match:
            raise HTTPException(
                status_code=422,
                detail="No se pudo interpretar la extracción del informe existente.",
            )
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail="El LLM no devolvió un JSON válido al extraer el informe existente.",
            ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=422,
            detail="La extracción del informe existente no devolvió un objeto JSON.",
        )
    return data


def _extraer_texto_libre(
    texto: str,
    llm_router: LlmRouterService,
) -> dict[str, str | None]:
    """Extrae campos literales de un informe manual sin pedir una nueva decisión."""
    system = """Eres un extractor de datos de informes de atención de reclamos de EMAPA.
Tu tarea es COPIAR fragmentos literales del documento, no resumir, completar ni
reescribir. Devuelve exclusivamente un objeto JSON con estas claves:
- "fundamentacion": párrafo o párrafos literales que contienen el sustento
  normativo o técnico; usa null si no se distinguen claramente.
- "conclusion": párrafo literal que contiene la decisión final sobre el reclamo
  y su declaración FUNDADO o INFUNDADO. No confundas el cierre de atribuciones
  legales ni las constancias posteriores con la conclusión.
- "veredicto": "FUNDADO", "INFUNDADO" o null. Solo puede informarse si aparece
  expresamente en el documento.
No inventes una fundamentación ni decidas por tu cuenta el veredicto."""
    respuesta = llm_router.generar_json(
        mensajes=[
            MensajeLLM(rol="system", contenido=system),
            MensajeLLM(rol="user", contenido=f"DOCUMENTO:\n{texto}"),
        ],
        modelo_id=MODELO_EXTERNO_DEFAULT,
    )
    data = _parsear_json_extraccion(respuesta)

    conclusion = _texto(data.get("conclusion"))
    fundamentacion = _texto(data.get("fundamentacion")) or None
    veredicto_llm = _texto(data.get("veredicto")).upper() or None
    veredicto_texto = _extraer_veredicto(conclusion)

    if not conclusion:
        raise HTTPException(
            status_code=422,
            detail="El informe existente no contiene una conclusión identificable.",
        )
    if _normalizar_comparacion(conclusion) not in _normalizar_comparacion(texto):
        raise HTTPException(
            status_code=422,
            detail="La conclusión extraída no pertenece literalmente al informe recibido.",
        )
    if veredicto_llm not in _VEREDICTOS or veredicto_texto != veredicto_llm:
        raise HTTPException(
            status_code=422,
            detail=(
                "No se pudo validar un único veredicto FUNDADO o INFUNDADO "
                "dentro de la conclusión del informe existente."
            ),
        )
    if fundamentacion and _normalizar_comparacion(fundamentacion) not in _normalizar_comparacion(texto):
        logger.warning("[rehidratacion SYSCO] Se descarta fundamentación no literal devuelta por el LLM")
        fundamentacion = None

    return {
        "fundamentacion": fundamentacion,
        "conclusion": conclusion,
        "veredicto": veredicto_llm,
    }


def rehidratar_informe_desde_sysco(
    informe: InformeAtencion,
    datos: dict,
    llm_router: LlmRouterService,
) -> dict[str, str] | None:
    """Recupera informe, conciliación y resolución del detalle enviado por SYSCO.

    Devuelve ``None`` cuando no existe informe y un mapa de resúmenes cuando sí
    existe. El mapa puede estar vacío para texto manual: esa diferencia permite
    recalcular datos/problemas sin pedir al LLM nuevos resúmenes.
    """
    detalle = _detalle_sysco(datos)
    atencion = _ultimo_dict(detalle.get("datos_atencion"))
    resolucion = _ultimo_dict(detalle.get("datos_resolucion"))

    candidatos_considerando = (
        _texto(atencion.get("considerando")),
        _texto(detalle.get("considerando")),
    )
    considerando = next(
        (valor for valor in candidatos_considerando if valor.upper() not in _VALORES_PENDIENTES),
        "",
    )
    propuesta = _texto(atencion.get("propuestaeps"))
    texto_resolucion = _texto(resolucion.get("resuelve"))

    if not considerando:
        faltantes = [
            nombre
            for nombre, campo in (
                ("interna", "inspeccion_interna"),
                ("externa", "inspeccion_externa"),
            )
            if not codigo_inspeccion(datos, campo)
        ]
        # Si la sesión ya avanzó, una recarga con datos históricos parciales no
        # debe destruir ni bloquear el trabajo que permanece en memoria.
        if faltantes and not (informe.conclusion and informe.veredicto):
            raise HTTPException(
                status_code=409,
                detail=(
                    "No se puede iniciar la investigación porque faltan las "
                    f"inspecciones: {', '.join(faltantes)}."
                ),
            )
        return None

    extraido = _extraer_formato_generado(considerando, informe.medios_probatorios)
    origen = "formato_generado"
    if extraido is None:
        extraido = _extraer_texto_libre(considerando, llm_router)
        origen = "texto_libre"
    resumenes = extraido.get("resumenes", {})

    # La asignación se realiza solo después de validar por completo la
    # extracción, para no dejar un informe parcialmente rehidratado.
    informe.informe_texto_original = considerando
    informe.fundamentacion_normativa = extraido["fundamentacion"]
    informe.conclusion = extraido["conclusion"]
    informe.veredicto = extraido["veredicto"]

    if propuesta and propuesta.upper() not in _VALORES_PENDIENTES:
        if informe.propuesta_conciliacion is None:
            # SYSCO solo garantiza la propuesta de la EPS; no se debe interpretar
            # la ausencia de postura del reclamante como una aceptación.
            informe.propuesta_conciliacion = Conciliacion(
                propuesta_reclamante="",
                puntos_acuerdo="",
                puntos_desacuerdo="",
                observaciones="",
            )
        informe.propuesta_conciliacion.propuesta_empresa = propuesta

    if texto_resolucion and texto_resolucion.upper() not in _VALORES_PENDIENTES:
        informe.resolucion = texto_resolucion

    logger.info(
        "[rehidratacion SYSCO] reclamo=%s | origen=%s | veredicto=%s | propuesta=%s | resolucion=%s",
        informe.reclamo, origen, informe.veredicto, bool(propuesta), bool(texto_resolucion),
    )
    return resumenes


def crear_informe_desde_datos(
    datos: dict,
    codreclamo: str,
    codcliente: str,
    token: str,
    sesion_id: str | None,
    creado_por: str | None = None,
) -> InformeAtencion:
    """Crea la entidad de dominio del informe de atención a partir del detalle
    CRUDO del reclamo (el mismo JSON que devuelve EMAPA en
    `reclamo/obtener/detalle/...`, con su clave `data`). Extrae los campos, arma
    el `Reclamo`, crea los metadatos en el store y guarda el token.

    NO llama a EMAPA: el detalle ya viene dado (lo tiene el frontend desde la
    pantalla de detalle, o lo acaba de traer la búsqueda). Es el núcleo común de
    la búsqueda manual, el flujo automatizado y el arranque desde el frontend.

    Lanza `ReclamoEnAtencionError` (que los endpoints traducen a 409) si otra
    sesión ya está atendiendo el mismo reclamo."""
    motivo = campo_reclamo(datos, "motivo")
    clasificacion = campo_reclamo(datos, "desCodReclamo")
    codigo_tipo_reclamo = campo_reclamo(datos, "codreclamo")
    codinspeccion_interna = codigo_inspeccion(datos, "inspeccion_interna")
    codinspeccion_externa = codigo_inspeccion(datos, "inspeccion_externa")
    if not codinspeccion_interna:
        logger.warning("[informe] Reclamo %s sin inspección interna vinculada", codreclamo)
    if not codinspeccion_externa:
        logger.warning("[informe] Reclamo %s sin inspección externa vinculada", codreclamo)

    datos_reclamo = Reclamo(
        codcliente=campo_reclamo(datos, "codcliente") or None,
        reclamante=campo_reclamo(datos, "reclamante") or None,
        propietario=campo_reclamo(datos, "propietario") or None,
        dni=campo_reclamo(datos, "dniCliente") or campo_reclamo(datos, "nrodocident") or None,
        tipo_reclamo=campo_reclamo(datos, "descTipoReclamo") or None,
        clasificacion_reclamo=clasificacion or None,
        motivo_reclamo=motivo or None,
        meses_reclamados=campo_reclamo(datos, "mesanio") or None,
        fecha_recepcion=campo_reclamo(datos, "fecharec") or None,
        estado_reclamo=campo_reclamo(datos, "descEstadoRec") or None,
        codinspeccion_interna=codinspeccion_interna,
        codinspeccion_externa=codinspeccion_externa,
    )

    informe = informe_store.crear_metadata(
        codreclamo=codreclamo,
        suministro=codcliente,
        datos_reclamo=datos_reclamo,
        sesion_id=sesion_id,
        creado_por=creado_por,
    )
    informe.medios_probatorios = obtener_medios_probatorios(codigo_tipo_reclamo)
    informe_store.guardar_token(codreclamo, token)
    return informe


async def buscar_y_crear_informe_o_lanzar(
    codsede: str, codsuc: str, codreclamo: str, codcliente: str,
    token: str, sesion_id: str | None, creado_por: str | None,
    api: PuertoEmapaAPI,
) -> InformeAtencion:
    """Búsqueda del reclamo + creación de metadatos del informe, propia del
    flujo automatizado: a diferencia de GET /reclamo/... (que devuelve el error
    en el cuerpo con 200, pensado para que el usuario lo vea como mensaje de
    búsqueda), acá cualquier fallo lanza HTTPException y corta el proceso."""
    try:
        datos = api.buscar_reclamo(codsede, codsuc, codreclamo, codcliente)
    except EmapaSinDatosError:
        logger.warning(
            "[informe-atencion] Reclamo no encontrado | codsede=%s codsuc=%s codcliente=%s codreclamo=%s",
            codsede, codsuc, codcliente, codreclamo,
        )
        raise HTTPException(
            status_code=404,
            detail="No se encontró el reclamo. Verifica el código de sede, sucursal, cliente y reclamo.",
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[informe-atencion] Error EMAPA: %s", str(e))
        raise HTTPException(status_code=502, detail=str(e))

    try:
        informe = crear_informe_desde_datos(
            datos, codreclamo, codcliente, token, sesion_id, creado_por,
        )
    except ReclamoEnAtencionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return informe
