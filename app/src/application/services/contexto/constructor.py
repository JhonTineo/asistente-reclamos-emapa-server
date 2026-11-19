"""Constructor de contexto: arma cada llamada al LLM a partir de capas.

Uso desde un paso del workflow:

    ctx = constructor_contexto.construir(
        "resumen_medio", informe, medio_id=..., medio_nombre=..., datos=..., hechos=...,
    )
    texto = ctx.ejecutar_texto(llm_router, modelo_id)

``construir`` lee la especificación del paso, arma las capas en el orden fijo
del catálogo, las recorta si no caben en el presupuesto y devuelve un
``Contexto`` con los mensajes listos. ``ejecutar_texto`` / ``ejecutar_json``
llaman al LLM y registran la llamada (paso, skills con su versión, tamaño de
cada capa, texto enviado, respuesta, duración y error). Si el registro falla,
solo se avisa en el log: nunca interrumpe el análisis.
"""

import logging
import time
from dataclasses import dataclass, field

from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.ports.registro_llamadas_port import PuertoRegistroLlamadas
from app.src.application.ports.skill_repository_port import PuertoRepositorioSkills
from app.src.application.services.contexto import capas as render
from app.src.application.services.contexto.capas import CATALOGO, Capa
from app.src.application.services.llm import uso_tokens
from app.src.application.services.contexto.especificaciones import (
    ContextSpec, obtener_especificacion,
)
from app.src.core.model.informe_atencion import InformeAtencion, ProblemaNormado
from app.src.core.model.skill import SECCION_INSTRUCCIONES, Skill

logger = logging.getLogger("contexto")

CARACTERES_POR_TOKEN = 4   # estimación suficiente para no pasar la ventana


def estimar_tokens(texto: str) -> int:
    return -(-len(texto) // CARACTERES_POR_TOKEN)   # división hacia arriba


@dataclass
class Contexto:
    paso: str
    codreclamo: str | None
    capas: list[Capa]
    skills: list[Skill] = field(default_factory=list)
    presupuesto_tokens: int = 0
    registro: PuertoRegistroLlamadas | None = None
    max_tokens_respuesta: int | None = None

    # -------------------------------------------------------------- #
    @property
    def system(self) -> str:
        return "\n\n".join(c.contenido for c in self.capas if c.va_en_system and c.contenido)

    @property
    def usuario(self) -> str:
        return "\n\n".join(c.contenido for c in self.capas if not c.va_en_system and c.contenido)

    @property
    def mensajes(self) -> list[MensajeLLM]:
        return [MensajeLLM(rol="system", contenido=self.system),
                MensajeLLM(rol="user", contenido=self.usuario)]

    @property
    def tokens_estimados(self) -> int:
        return estimar_tokens(self.system) + estimar_tokens(self.usuario)

    @property
    def versiones_skills(self) -> list[str]:
        return [s.version_completa for s in self.skills]

    def resumen_capas(self, uso: dict | None = None) -> dict:
        """Lo que se guarda en llamadas_llm.capas: tamaño de cada capa y, si el
        proveedor lo informó, los tokens reales (entrada, cacheados, salida)."""
        resumen = {
            "capas": {
                c.nombre: {"caracteres": c.caracteres, "recortada": c.recortada}
                for c in self.capas
            },
            "tokens_aprox": self.tokens_estimados,
            "presupuesto": self.presupuesto_tokens,
        }
        if uso:
            resumen["uso"] = uso
        return resumen

    # -------------------------------------------------------------- #
    def _extras(self) -> dict:
        # Solo se pasa el tope cuando el paso define uno: así los routers que
        # no lo conocen (pruebas, adaptadores antiguos) siguen funcionando.
        return {"max_tokens": self.max_tokens_respuesta} if self.max_tokens_respuesta else {}

    def ejecutar_texto(self, llm_router, modelo_id: str) -> str:
        """Texto redactado para el informe: se le quitan los identificadores
        internos de hechos que el modelo haya podido copiar. En el registro
        queda la respuesta tal como llegó."""
        respuesta = self._ejecutar(
            lambda mensajes, modelo_id: llm_router.generar_texto(
                mensajes=mensajes, modelo_id=modelo_id, **self._extras(),
            ),
            modelo_id, llm_router,
        )
        return render.quitar_identificadores(respuesta) if isinstance(respuesta, str) else respuesta

    def ejecutar_json(self, llm_router, modelo_id: str, esquema: dict | None = None) -> str:
        return self._ejecutar(
            lambda mensajes, modelo_id: llm_router.generar_json(
                mensajes=mensajes, modelo_id=modelo_id, esquema=esquema, **self._extras(),
            ),
            modelo_id, llm_router,
        )

    def _ejecutar(self, llamar, modelo_id: str, llm_router=None) -> str:
        logger.debug(
            "[CONTEXTO] paso=%s | reclamo=%s | tokens≈%d/%d | skills=%s",
            self.paso, self.codreclamo, self.tokens_estimados, self.presupuesto_tokens,
            ", ".join(self.versiones_skills) or "ninguna",
        )
        logger.debug("[CONTEXTO %s][SYSTEM]\n%s", self.paso, self.system)
        logger.debug("[CONTEXTO %s][USER]\n%s", self.paso, self.usuario)
        inicio = time.perf_counter()
        uso_tokens.limpiar()
        respuesta, error = None, None
        try:
            respuesta = llamar(mensajes=self.mensajes, modelo_id=modelo_id)
            return respuesta
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            # Con modelo "auto" (o con respaldo entre proveedores) el id pedido
            # no dice quién respondió: el router lo informa tras la llamada.
            proveedor, modelo_real = getattr(llm_router, "ultimo_uso", None) or (None, None)
            segundos = time.perf_counter() - inicio
            uso = uso_tokens.ultimo()
            self._log_llamada(modelo_real or modelo_id, proveedor, segundos, uso, respuesta, error)
            self._registrar(modelo_real or modelo_id, respuesta, error, segundos, proveedor, uso)

    def _log_llamada(self, modelo_id: str, proveedor, segundos: float, uso: dict | None,
                     respuesta, error) -> None:
        """La línea que sirve para optimizar: una por llamada, con el tiempo y
        los tokens reales (cacheados incluidos). El prompt completo queda en
        llamadas_llm; en consola solo con el nivel DEBUG."""
        uso = uso or {}
        logger.info(
            "[TIEMPOS] llm | paso=%s | reclamo=%s | %.2fs | entrada=%s (cache=%s) | salida=%s | "
            "proveedor=%s | modelo=%s%s",
            self.paso, self.codreclamo, segundos,
            uso.get("entrada", f"≈{self.tokens_estimados}"), uso.get("cacheados", "?"),
            uso.get("salida", "?"), proveedor or "?", modelo_id,
            f" | ERROR={error}" if error else "",
        )

    def _registrar(self, modelo_id: str, respuesta, error, segundos: float,
                   proveedor: str | None = None, uso: dict | None = None) -> None:
        if self.registro is None:
            return
        try:
            self.registro.registrar_llamada(
                proveedor=proveedor,
                codreclamo=self.codreclamo,
                paso=self.paso,
                skill=", ".join(s.id for s in self.skills) or None,
                skill_version=", ".join(self.versiones_skills) or None,
                modelo=modelo_id,
                capas=self.resumen_capas(uso),
                system=self.system,
                usuario=self.usuario,
                respuesta=respuesta if isinstance(respuesta, str) else None,
                duracion_ms=int(segundos * 1000),
                error=error,
            )
        except Exception:  # noqa: BLE001
            logger.warning("[CONTEXTO] No se pudo registrar la llamada del paso %s", self.paso,
                           exc_info=True)


class ContextBuilder:

    def __init__(
        self,
        skills: PuertoRepositorioSkills | None = None,
        registro: PuertoRegistroLlamadas | None = None,
    ):
        self._skills = skills
        self.registro = registro

    def configurar(self, *, skills: PuertoRepositorioSkills | None = None,
                   registro: PuertoRegistroLlamadas | None = None) -> None:
        if skills is not None:
            self._skills = skills
        self.registro = registro

    @property
    def skills(self) -> PuertoRepositorioSkills:
        if self._skills is None:
            # Sin configuración explícita (p.ej. en pruebas) se usan los archivos
            # de app/src/skills. En la app, main.py lo configura al arrancar.
            from app.src.infrastructure.adapters.skills.skill_file_repository import repositorio_skills
            self._skills = repositorio_skills()
        return self._skills

    def skill_de_medio(self, medio_id: str) -> Skill | None:
        return self.skills.para_medio(medio_id)

    # -------------------------------------------------------------- #
    def construir(self, paso: str, informe: InformeAtencion | None = None, **datos) -> Contexto:
        """``datos`` según el paso: medio_id, medio_nombre, datos (dict del
        medio), hechos (lista de ProblemaNormado), enfoque, clasificacion,
        criterios_excluidos (IDs de criterios que no se envían al modelo)."""
        spec = obtener_especificacion(paso)
        skills_y_secciones = self._skills_del_paso(spec, informe, datos)
        hechos = self._hechos_del_paso(spec, informe, datos)
        datos = {**datos, "hechos": hechos}

        capas = []
        for nombre in CATALOGO:   # el catálogo fija el orden
            if nombre not in spec.capas:
                continue
            contenido = self._render(nombre, spec, informe, datos, skills_y_secciones, hechos)
            if contenido:
                capas.append(Capa(nombre, contenido))

        contexto = Contexto(
            paso=paso,
            codreclamo=informe.reclamo if informe else datos.get("codreclamo"),
            capas=capas,
            skills=[*(self.skills.base() if "rol_base" in spec.capas else []),
                    *(s for s, _ in skills_y_secciones)],
            presupuesto_tokens=spec.presupuesto_tokens,
            registro=self.registro,
            max_tokens_respuesta=spec.max_tokens_respuesta,
        )
        self._ajustar_al_presupuesto(contexto, spec)
        return contexto

    def criterios_del_paso(self, paso: str, informe: InformeAtencion | None = None,
                           **datos) -> dict:
        """Criterios vigentes (id -> Criterio) de las skills que el paso usaría
        para este caso. Permite decidir en código cuáles descartar ANTES de
        construir el contexto (ver ``criterios_excluidos``)."""
        spec = obtener_especificacion(paso)
        return {c.id: c for skill, _ in self._skills_del_paso(spec, informe, datos)
                for c in skill.criterios_vigentes()}

    def _skills_del_paso(self, spec: ContextSpec, informe, datos) -> list[tuple[Skill, list[str]]]:
        elegidas: list[tuple[Skill, list[str]]] = []
        if spec.skill_paso:
            skill = self.skills.para_paso(spec.paso)
            if skill is None:
                raise KeyError(f"Falta la skill del paso '{spec.paso}' (skills/pasos/{spec.paso}.md)")
            elegidas.append((skill, [SECCION_INSTRUCCIONES]))
        if spec.secciones_tipo:
            clasificacion = (informe.clasificacion if informe else None) or datos.get("clasificacion")
            tipo = self.skills.para_tipo_reclamo(clasificacion=clasificacion)
            if tipo:
                elegidas.append((tipo, list(spec.secciones_tipo)))
        if spec.secciones_medio:
            if spec.medios_del_caso and informe:
                medios = [b.medio_id for b in informe.bloques]
            else:
                medios = [datos["medio_id"]] if datos.get("medio_id") else []
            for medio_id in medios:
                skill = self.skills.para_medio(medio_id)
                if skill:
                    elegidas.append((skill, list(spec.secciones_medio)))
        return elegidas

    @staticmethod
    def _hechos_del_paso(spec: ContextSpec, informe, datos) -> list[ProblemaNormado]:
        if datos.get("hechos") is not None:
            return list(datos["hechos"])
        if informe is None:
            return []
        if spec.hechos == "todos":
            return [h for b in informe.bloques for h in b.hechos]
        medio_id = datos.get("medio_id")
        return [h for b in informe.bloques if b.medio_id == medio_id for h in b.hechos]

    def _render(self, nombre, spec, informe, datos, skills_y_secciones, hechos) -> str:
        if nombre == "rol_base":
            return render.render_rol_base(self.skills.base(), spec.secciones_base)
        if nombre == "skill":
            return render.render_skills(
                skills_y_secciones, frozenset(datos.get("criterios_excluidos") or ()),
            )
        if nombre == "normativa":
            return render.render_normativa(hechos)
        if nombre == "reclamo":
            return render.render_reclamo(informe, datos.get("clasificacion"))
        if nombre == "objetivos":
            return render.render_objetivos(informe)
        if nombre == "hechos":
            if spec.hechos == "todos" and informe is not None:
                # agrupados por medio, con los hechos del caso completo primero
                return render.render_hechos_por_medio(informe, datos.get("hechos_caso"))
            titulo = f"Hechos de {datos['medio_nombre']}" if datos.get("medio_nombre") else "Hechos del caso"
            return render.render_hechos(hechos, titulo)
        if nombre == "datos_medio":
            if datos.get("datos") is None:
                return ""
            return render.render_datos_medio(
                datos.get("medio_nombre", ""), render.depurar_datos(datos["datos"], hechos),
            )
        if nombre == "textos_previos":
            return render.render_textos_previos(informe, datos.get("medio_id")) if informe else ""
        if nombre == "instrucciones":
            return (datos.get("instrucciones") or "").strip()
        if nombre == "entrada":
            return (datos.get("entrada") or "").strip()
        if nombre == "tarea":
            return spec.tarea(datos)
        raise KeyError(f"Capa desconocida: {nombre}")

    # -------------------------------------------------------------- #
    def llamar(self, paso: str, llm_router, modelo_id: str, *,
               informe: InformeAtencion | None = None, entrada: str = "",
               instrucciones: str | None = None, codreclamo: str | None = None,
               esquema: dict | None = None) -> str:
        """Atajo para los pasos que preparan sus propios datos: arma el
        contexto del paso y ejecuta la llamada (texto o JSON según su
        especificación), registrándola."""
        contexto = self.construir(paso, informe, entrada=entrada,
                                  instrucciones=instrucciones, codreclamo=codreclamo)
        if obtener_especificacion(paso).salida == "json":
            return contexto.ejecutar_json(llm_router, modelo_id, esquema)
        return contexto.ejecutar_texto(llm_router, modelo_id)

    @staticmethod
    def _ajustar_al_presupuesto(contexto: Contexto, spec: ContextSpec) -> None:
        exceso = contexto.tokens_estimados - spec.presupuesto_tokens
        if exceso <= 0:
            return
        por_nombre = {c.nombre: c for c in contexto.capas}
        for nombre in spec.recortar_primero:
            capa = por_nombre.get(nombre)
            if capa is None or exceso <= 0:
                continue
            capa.recortar(exceso * CARACTERES_POR_TOKEN)
            exceso = contexto.tokens_estimados - spec.presupuesto_tokens
            logger.warning(
                "[CONTEXTO] paso=%s: capa '%s' recortada para respetar el presupuesto de %d tokens",
                spec.paso, nombre, spec.presupuesto_tokens,
            )
        if exceso > 0:
            logger.warning(
                "[CONTEXTO] paso=%s: el contexto supera el presupuesto en ≈%d tokens "
                "aun después de recortar (las capas protegidas no se recortan)",
                spec.paso, exceso,
            )


# Constructor compartido del proceso. main.py le conecta el registro de llamadas.
constructor_contexto = ContextBuilder()
