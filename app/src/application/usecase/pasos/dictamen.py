"""Paso de dictamen: evalúa los criterios de las skills contra los hechos del caso.

Reemplaza la evaluación por objetivos. Funciona en tres tiempos:

1. **El LLM evalúa cada criterio** (con el contexto ``dictamen``: método y
   criterios de las skills, todos los hechos con su ID, normativa, objetivos
   como guía): ``aplica`` / ``no_aplica`` / ``no_determinable``, a quién
   favorece y qué hechos lo sustentan.
2. **Un verificador en código** revisa la respuesta: que los criterios y hechos
   citados existan, que todo criterio que aplica cite hechos, y que se hayan
   considerado las alegaciones del usuario y las pruebas faltantes. Si falla,
   se reintenta UNA vez con la lista de errores como crítica; si vuelve a
   fallar, el caso queda en ``error_evaluacion`` con los motivos.
3. **Una regla fija decide el veredicto** a partir de la fuerza de cada
   criterio que aplica (definida en la skill, no por el modelo):
   - algún criterio pide revisión, o hay decisivos en ambas direcciones → revisión;
   - decisivo a favor del usuario → FUNDADO; decisivo a favor de la empresa → INFUNDADO;
   - sin decisivos → INFUNDADO (régimen de diferencia de lecturas, RC Art. 93),
     salvo que el modelo proponga FUNDADO solo con indicios → revisión.
   Si el veredicto se apoya solo en criterios ``por_confirmar``, se emite con
   una advertencia.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.informe.hechos_caso import hechos_del_caso
from app.src.application.services.llm.llm_router_service import MODELO_EXTERNO_DEFAULT
from app.src.core.model.informe_atencion import InformeAtencion, MotivoEvaluacion, ProblemaNormado
from app.src.core.model.skill import Criterio

logger = logging.getLogger("paso.dictamen")

APLICA, NO_APLICA, NO_DETERMINABLE, NO_EVALUADO = "aplica", "no_aplica", "no_determinable", "no_evaluado"
VALORES_APLICA = (APLICA, NO_APLICA, NO_DETERMINABLE)
FAVORECE_VALIDOS = ("usuario", "empresa", "revision")
INTENTOS = 2   # evaluaciones de contenido: la primera + un reintento con la crítica
# Reintentos aparte para respuestas que no llegan a ser un JSON (cortadas o
# vacías): un fallo de formato no debe gastar el reintento de contenido.
REINTENTOS_FORMATO = 1

EXPLICACION_DESCARTADO = "Ningún hecho del caso cumple la condición de este criterio ({condicion})."
CRITICA_CORTADA = (
    "Tu respuesta anterior se cortó antes de cerrar el JSON por ser demasiado larga. "
    "Responde de nuevo con el JSON completo y más breve: una sola frase corta en la "
    "\"explicacion\" de los criterios que no aplican y un \"razonamiento\" de dos o "
    "tres oraciones."
)


@dataclass
class Factor:
    criterio: str
    nombre: str
    aplica: str
    favorece: str | None
    hechos: list[str]
    explicacion: str
    fuerza: str
    estado_criterio: str


@dataclass
class Dictamen:
    veredicto: str | None                  # FUNDADO | INFUNDADO | None (sin decisión)
    estado: str                            # completada | requiere_revision | error_evaluacion
    factores: list[Factor] = field(default_factory=list)
    motivos: list[MotivoEvaluacion] = field(default_factory=list)
    conflictos: list[str] = field(default_factory=list)
    alegaciones: list[dict] = field(default_factory=list)
    pruebas_faltantes: list[str] = field(default_factory=list)
    veredicto_propuesto: str | None = None
    razonamiento: str = ""
    regla: str = ""                        # qué rama de la regla decidió
    hechos_caso: list[dict] = field(default_factory=list)
    intentos: int = 0
    skills: list[str] = field(default_factory=list)

    @property
    def aplicables(self) -> list[Factor]:
        return [f for f in self.factores if f.aplica == APLICA]

    def hechos_citados(self) -> list[str]:
        return sorted({h for f in self.aplicables for h in f.hechos})

    def a_dict(self) -> dict:
        return asdict(self)


class RespuestaInvalida(Exception):
    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("; ".join(errores))


class RespuestaSinFormato(RespuestaInvalida):
    """La respuesta no llegó a ser un JSON utilizable (vacía, cortada o mal
    formada): no hay contenido que criticar, solo se vuelve a pedir."""
    def __init__(self, errores: list[str], cortada: bool = False):
        super().__init__(errores)
        self.cortada = cortada


def _parece_cortada(texto: str) -> bool:
    """Empieza un objeto JSON pero no lo cierra: se agotó el tope de tokens."""
    limpio = re.sub(r"`+\s*$", "", texto).rstrip()
    return "{" in limpio and not limpio.endswith("}")


def _parsear(texto: str) -> dict:
    texto = (texto or "").strip()
    if not texto:
        raise RespuestaSinFormato(["La respuesta llegó vacía."])
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        cortada = RespuestaSinFormato(
            ["La respuesta se cortó antes de cerrar el JSON (tope de tokens)."], cortada=True,
        )
        encontrado = re.search(r"\{.*\}", texto, re.DOTALL)
        if not encontrado:
            raise cortada if _parece_cortada(texto) else RespuestaSinFormato(
                ["La respuesta no es un objeto JSON."])
        try:
            data = json.loads(encontrado.group())
        except json.JSONDecodeError as exc:
            if _parece_cortada(texto):
                raise cortada from exc
            raise RespuestaSinFormato([f"El JSON no es válido: {exc}"]) from exc
    if not isinstance(data, dict) or not isinstance(data.get("factores"), list):
        raise RespuestaInvalida(["Falta la lista \"factores\"."])
    return data


def _valor_como_texto(valor) -> str:
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor).strip().lower()


def _cumple_parte(hecho: ProblemaNormado, parte: str) -> bool:
    """``tipo`` o ``tipo.campo=valor`` (valor: true/false/null o texto)."""
    tipo, _, resto = parte.strip().partition(".")
    if hecho.tipo != tipo:
        return False
    if not resto:
        return True
    campo, _, esperado = resto.partition("=")
    return _valor_como_texto((hecho.valor or {}).get(campo)) == esperado.strip().lower()


def cumple_requisito(criterio: Criterio, citados: list[ProblemaNormado]) -> bool:
    """Algún requisito alternativo (|) se cumple: cada parte (&) la cumple
    alguno de los hechos citados. Sin requisitos, siempre se cumple."""
    if not criterio.requiere:
        return True
    return any(
        all(any(_cumple_parte(h, parte) for h in citados) for parte in alternativa.split("&"))
        for alternativa in criterio.requiere
    )


def completar_citas(criterio: Criterio, citados: list[ProblemaNormado],
                    todos: list[ProblemaNormado]) -> list[ProblemaNormado] | None:
    """Hechos que faltan citar para que ``citados`` cumpla la condición del
    criterio, tomados de ``todos`` los hechos del caso. Devuelve ``[]`` si ya
    se cumple, la lista más corta de hechos a agregar si alguna alternativa (|)
    se puede completar, o ``None`` si ningún hecho del caso la cumple.

    Existe porque el filtro previo (``criterios_sin_requisito``) evalúa la
    condición sobre TODOS los hechos, pero el modelo suele citar solo el hecho
    principal: en «vpaZona.operativa=false & horarioAbastecimiento.continuo=false»
    cita la VPA y omite el horario. La condición es objetiva y ya se sabe que el
    caso la cumple; completar la cita es más fiable que pedirle al modelo que
    adivine qué faltó, y evita que el caso termine en error de evaluación."""
    if cumple_requisito(criterio, citados):
        return []
    mejor: list[ProblemaNormado] | None = None
    for alternativa in criterio.requiere:
        agregar: list[ProblemaNormado] = []
        for parte in alternativa.split("&"):
            if any(_cumple_parte(h, parte) for h in citados + agregar):
                continue
            candidato = next((h for h in todos if _cumple_parte(h, parte)), None)
            if candidato is None:
                break
            agregar.append(candidato)
        else:
            if mejor is None or len(agregar) < len(mejor):
                mejor = agregar
    return mejor


def criterios_sin_requisito(criterios: dict[str, Criterio],
                            hechos: list[ProblemaNormado]) -> set[str]:
    """IDs de los criterios cuya condición («Requiere») no cumple NINGÚN hecho
    del caso. No pueden aplicar, así que se resuelven aquí y no se le preguntan
    al modelo: este solo ve el texto de cada hecho, no sus valores, y marcaba
    como atípico un consumo con atipico=false."""
    return {cid for cid, c in criterios.items()
            if c.requiere and not cumple_requisito(c, hechos)}


def verificar(data: dict, criterios: dict[str, Criterio],
              hechos: dict[str, ProblemaNormado],
              descartados: set[str] | frozenset[str] = frozenset(),
              ) -> tuple[list[Factor], list[str]]:
    """Convierte la respuesta en factores y devuelve los errores encontrados
    (vacío si la respuesta es válida). Los criterios que el modelo omitió se
    registran como ``no_evaluado`` sin considerarse un error. Los
    ``descartados`` (ver ``criterios_sin_requisito``) quedan como ``no_aplica``
    diga lo que diga el modelo sobre ellos."""
    errores: list[str] = []
    factores: dict[str, Factor] = {}
    for crudo in data["factores"]:
        if not isinstance(crudo, dict):
            errores.append("Hay un factor que no es un objeto.")
            continue
        cid = str(crudo.get("criterio") or "").strip()
        if cid in descartados:
            continue   # ya resuelto en código; no se le pidió al modelo
        criterio = criterios.get(cid)
        if criterio is None:
            if cid in hechos:
                errores.append(
                    f"\"{cid}\" es un HECHO, no un criterio: no lo pongas en \"criterio\". "
                    "Cítalo en \"hechos\" del criterio que corresponda, o, si es una "
                    "alegación que ningún criterio cubre, explícala en \"alegaciones\"."
                )
            else:
                errores.append(f"El criterio \"{cid}\" no existe entre los criterios del caso.")
            continue
        if cid in factores:
            errores.append(f"El criterio {cid} aparece más de una vez.")
            continue
        aplica = str(crudo.get("aplica") or "").strip()
        if aplica not in VALORES_APLICA:
            errores.append(f"{cid}: \"aplica\" debe ser aplica, no_aplica o no_determinable.")
            continue
        citados = [str(h).strip() for h in crudo.get("hechos") or [] if str(h).strip()]
        desconocidos = [h for h in citados if h not in hechos]
        if desconocidos:
            errores.append(f"{cid}: cita hechos que no existen ({', '.join(desconocidos)}).")
        favorece = str(crudo.get("favorece") or "").strip() or None
        if aplica == APLICA:
            validos = [hechos[h] for h in citados if h in hechos]
            if not validos:
                errores.append(f"{cid}: aplica, pero no cita ningún hecho que lo sustente.")
            else:
                faltantes = completar_citas(criterio, validos, list(hechos.values()))
                if faltantes is None:
                    errores.append(
                        f"{cid}: marcado como aplica, pero ningún hecho del caso cumple su "
                        f"condición ({' o '.join(criterio.requiere)}). Revisa el valor de los "
                        "hechos: si la condición no se cumple, el criterio no aplica."
                    )
                elif faltantes:
                    # La condición se cumple con hechos del caso que el modelo no
                    # citó: se agregan a la cita en vez de rechazar la respuesta.
                    citados = citados + [h.id for h in faltantes if h.id not in citados]
                    logger.info(
                        "[DICTAMEN] %s: se completan las citas con %s para cumplir su condición",
                        cid, [h.id for h in faltantes],
                    )
            if favorece not in FAVORECE_VALIDOS:
                errores.append(f"{cid}: aplica, pero \"favorece\" debe ser usuario, empresa o revision.")
        factores[cid] = Factor(
            criterio=cid, nombre=criterio.nombre, aplica=aplica,
            favorece=favorece if aplica == APLICA else None,
            hechos=[h for h in citados if h in hechos],
            explicacion=str(crudo.get("explicacion") or "").strip(),
            fuerza=criterio.fuerza, estado_criterio=criterio.estado,
        )

    # Las alegaciones y las pruebas faltantes deben haberse considerado: citadas
    # en algún criterio o, para las alegaciones, tratadas en "alegaciones".
    en_criterios = {h for f in factores.values() for h in f.hechos}
    alegaciones_tratadas = en_criterios | {
        str(a.get("hecho")).strip() for a in data.get("alegaciones") or []
        if isinstance(a, dict) and str(a.get("explicacion") or "").strip()
    }
    for hecho in hechos.values():
        considerado = (hecho.id in en_criterios if hecho.tipo == "pruebaFaltante"
                       else hecho.id in alegaciones_tratadas)
        if hecho.tipo in ("pruebaFaltante", "alegacionDiscontinuidad") and not considerado:
            que = "la prueba faltante" if hecho.tipo == "pruebaFaltante" else "la alegación del usuario"
            errores.append(f"No consideraste {que} {hecho.id}: cítala en el criterio que corresponda.")

    for cid, criterio in criterios.items():
        if cid in descartados:
            factores[cid] = Factor(
                cid, criterio.nombre, NO_APLICA, None, [],
                EXPLICACION_DESCARTADO.format(condicion=" o ".join(criterio.requiere)),
                criterio.fuerza, criterio.estado,
            )
        elif cid not in factores:
            factores[cid] = Factor(cid, criterio.nombre, NO_EVALUADO, None, [], "",
                                   criterio.fuerza, criterio.estado)
    # En el orden de las skills, para que el dictamen se lea igual en cada corrida.
    return [factores[cid] for cid in criterios], errores


def resolver(factores: list[Factor], propuesta: str | None) -> tuple[str | None, str, list[MotivoEvaluacion]]:
    """Regla fija de resolución. Devuelve (veredicto o None, rama, motivos)."""
    aplicables = [f for f in factores if f.aplica == APLICA]
    revision = [f for f in aplicables if f.favorece == "revision"]
    du = [f for f in aplicables if f.fuerza == "decisivo" and f.favorece == "usuario"]
    de = [f for f in aplicables if f.fuerza == "decisivo" and f.favorece == "empresa"]

    def motivo(codigo, afectados, descripcion, accion):
        ids = ", ".join(f.criterio for f in afectados)
        return MotivoEvaluacion(codigo=codigo, accion_necesaria=accion,
                                descripcion=f"{descripcion} ({ids})" if ids else descripcion)

    if revision:
        return None, "criterio_pide_revision", [motivo(
            "CRITERIO_PIDE_REVISION", revision,
            "Un criterio aplicable indica que la evidencia no permite decidir sin revisión.",
            "Revisar la evidencia señalada y resolver la contradicción.")]
    if du and de:
        return None, "decisivos_en_conflicto", [motivo(
            "DECISIVOS_EN_CONFLICTO", du + de,
            "Hay criterios decisivos a favor del usuario y de la empresa a la vez.",
            "El especialista debe decidir cuál prevalece en este caso.")]
    if du:
        veredicto, rama, base = "FUNDADO", "decisivo_usuario", du
    elif de:
        veredicto, rama, base = "INFUNDADO", "decisivo_empresa", de
    elif (propuesta or "").upper() == "FUNDADO":
        return None, "fundado_solo_con_indicios", [motivo(
            "FUNDADO_SOLO_CON_INDICIOS", [f for f in aplicables if f.favorece == "usuario"],
            "El modelo propone FUNDADO, pero ningún criterio decisivo lo sustenta.",
            "Revisar si alguno de los indicios debería decidir el caso.")]
    else:
        return "INFUNDADO", "sin_decisivos", []

    motivos = []
    if base and all(f.estado_criterio == "por_confirmar" for f in base):
        motivos.append(motivo(
            "CRITERIO_POR_CONFIRMAR", base,
            "El veredicto se apoya en criterios pendientes de validar con el especialista.",
            "Confirmar el criterio con el especialista antes de notificar."))
    return veredicto, rama, motivos


class PasoDictamen:

    def __init__(self, llm_router, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

    def dictaminar(self, informe: InformeAtencion) -> Dictamen:
        hechos_caso = hechos_del_caso(informe)
        hechos = {h.id: h for b in informe.bloques for h in b.hechos if h.id}
        hechos.update({h.id: h for h in hechos_caso})

        # Los criterios con condición que ningún hecho cumple se resuelven en
        # código (no_aplica) y no se envían al modelo.
        criterios = constructor_contexto.criterios_del_paso("dictamen", informe)
        descartados = criterios_sin_requisito(criterios, list(hechos.values()))
        if descartados:
            logger.info("[DICTAMEN] Criterios descartados por su condición: %s", sorted(descartados))

        critica: list[str] | None = None
        dictamen = Dictamen(veredicto=None, estado="error_evaluacion",
                            hechos_caso=[asdict(h) for h in hechos_caso])
        data, factores, errores = {}, [], []
        fallos_contenido = fallos_formato = 0
        while True:
            contexto = constructor_contexto.construir(
                "dictamen", informe, hechos_caso=hechos_caso, critica=critica,
                criterios_excluidos=descartados,
                criterios_descartados=[f"{cid} · {criterios[cid].nombre}"
                                       for cid in criterios if cid in descartados],
            )
            dictamen.skills = contexto.versiones_skills
            dictamen.intentos += 1
            try:
                data = _parsear(contexto.ejecutar_json(self.llm_router, self.model_id))
                factores, errores = verificar(data, criterios, hechos, descartados)
            except RespuestaSinFormato as exc:
                data, factores, errores = {}, [], exc.errores
                fallos_formato += 1
                logger.warning("[DICTAMEN] Respuesta sin formato (%d): %s", fallos_formato, errores)
                if fallos_formato > REINTENTOS_FORMATO:
                    break
                critica = [CRITICA_CORTADA] if exc.cortada else errores
                continue
            except RespuestaInvalida as exc:
                data, factores, errores = {}, [], exc.errores
            if not errores:
                break
            fallos_contenido += 1
            logger.warning("[DICTAMEN] Evaluación %d con %d errores: %s",
                           fallos_contenido, len(errores), errores)
            if fallos_contenido >= INTENTOS:
                break
            critica = errores
        if errores:
            dictamen.motivos = [MotivoEvaluacion(
                codigo="DICTAMEN_INVALIDO",
                descripcion="El dictamen no pasó la verificación tras reintentar: " + "; ".join(errores),
                accion_necesaria="Reintentar la evaluación o revisar el caso manualmente.",
            )]
            dictamen.factores = factores
            return dictamen

        veredicto, regla, motivos = resolver(factores, data.get("veredicto_propuesto"))
        dictamen.veredicto = veredicto
        dictamen.estado = "completada" if veredicto else "requiere_revision"
        dictamen.factores = factores
        dictamen.motivos = motivos
        dictamen.regla = regla
        dictamen.conflictos = [str(c) for c in data.get("conflictos") or [] if str(c).strip()]
        dictamen.alegaciones = [a for a in data.get("alegaciones") or [] if isinstance(a, dict)]
        dictamen.pruebas_faltantes = [str(p) for p in data.get("pruebas_faltantes") or [] if str(p).strip()]
        dictamen.veredicto_propuesto = str(data.get("veredicto_propuesto") or "").upper() or None
        dictamen.razonamiento = str(data.get("razonamiento") or "").strip()
        if veredicto and dictamen.veredicto_propuesto not in (None, veredicto):
            logger.info("[DICTAMEN] El modelo propuso %s; la regla (%s) decidió %s",
                        dictamen.veredicto_propuesto, regla, veredicto)
        logger.info("[DICTAMEN] reclamo=%s | veredicto=%s | regla=%s | aplicables=%s | intentos=%d",
                    informe.reclamo, veredicto, regla,
                    [f"{f.criterio}:{f.favorece}" for f in dictamen.aplicables], dictamen.intentos)
        return dictamen
