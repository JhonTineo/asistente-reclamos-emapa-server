"""Carga las skills desde los archivos Markdown de ``app/src/skills``.

Lee ``tipos/*.md`` y ``medios/*.md``, valida su formato (ver el README de esa
carpeta) y las expone como objetos ``Skill``. Una skill con errores no se carga,
pero el error queda registrado (``errores()``) y en el log: un archivo mal
editado no debe tumbar el análisis de los demás medios.

Los archivos se releen solos cuando cambian en disco: editar una skill no
requiere reiniciar el servidor.

Para validar los archivos a mano:
    python -m app.src.infrastructure.adapters.skills.skill_file_repository
"""

import hashlib
import logging
import re
import sys
import threading
from pathlib import Path

import yaml

from app.src.core.model.skill import (
    ESTADOS_CRITERIO, ESTADOS_SKILL, FUERZAS_CRITERIO, SECCION_CRITERIOS, SECCION_LECTURA,
    SECCION_INSTRUCCIONES, SECCION_METODO, SECCION_ROL, TIPOS_SKILL, Criterio, Skill, normalizar_titulo,
)

logger = logging.getLogger("adapters.skills")

# Skills que viajan con el código (versionadas en git).
DIRECTORIO_SKILLS = Path(__file__).resolve().parents[3] / "skills"
# Reemplazos editables en producción sin redesplegar: un archivo aquí con la
# misma ruta relativa (p.ej. base/reglas_generales.md) reemplaza al del
# repositorio. En Docker es /code/volumes/skills, montado desde el host.
DIRECTORIO_REEMPLAZOS = Path(__file__).resolve().parents[5] / "volumes" / "skills"
SUBCARPETAS = ("base", "tipos", "medios", "pasos")

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECCION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_CRITERIO = re.compile(r"^###[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_TITULO_CRITERIO = re.compile(r"^(?P<id>[A-Z]{2,6}-\d{2,3})\s*[·:\-–—]\s*(?P<nombre>.+)$")
_META_CRITERIO = re.compile(r"^-[ \t]+\*\*(?P<clave>[^*:]+):\*\*[ \t]*(?P<valor>.*)$")
_CLAVES_META = {"estado": "estado", "fuente": "fuente", "pendiente": "pendiente",
                "fuerza": "fuerza", "requiere": "requiere"}
_CONDICION = re.compile(r"^[A-Za-z]+(\.[A-Za-z_]+=[^|&]+)?$")


class SkillInvalida(ValueError):
    def __init__(self, ruta: Path, errores: list[str]):
        self.ruta = ruta
        self.errores = errores
        super().__init__(f"{ruta.name}: " + "; ".join(errores))


def _como_tupla(valor) -> tuple[str, ...]:
    if valor is None:
        return ()
    if isinstance(valor, (list, tuple)):
        return tuple(str(v).strip() for v in valor if str(v).strip())
    return (str(valor).strip(),)


def _partir_secciones(cuerpo: str) -> dict[str, str]:
    marcas = list(_SECCION.finditer(cuerpo))
    secciones: dict[str, str] = {}
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(cuerpo)
        secciones[marca.group(1)] = cuerpo[marca.end():fin].strip()
    return secciones


def _parsear_criterios(texto: str, errores: list[str]) -> list[Criterio]:
    marcas = list(_CRITERIO.finditer(texto))
    if texto[: marcas[0].start() if marcas else len(texto)].strip():
        errores.append(f"'{SECCION_CRITERIOS}' tiene texto fuera de un criterio (###)")
    criterios: list[Criterio] = []
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        bloque = texto[marca.end():fin].strip("\n")
        titulo = _TITULO_CRITERIO.match(marca.group(1))
        if not titulo:
            errores.append(f"criterio '{marca.group(1)}': el título debe ser 'ID-01 · Nombre'")
            continue
        cid = titulo.group("id")

        # Metadatos: líneas "- **Clave:** valor" al inicio del bloque.
        meta: dict[str, str] = {}
        lineas = bloque.splitlines()
        inicio_cuerpo = 0
        for j, linea in enumerate(lineas):
            if not linea.strip() and not meta:
                continue
            encontrado = _META_CRITERIO.match(linea.strip())
            if not encontrado:
                inicio_cuerpo = j
                break
            clave = normalizar_titulo(encontrado.group("clave"))
            if clave not in _CLAVES_META:
                errores.append(f"criterio {cid}: metadato desconocido '{encontrado.group('clave')}'")
            else:
                meta[_CLAVES_META[clave]] = encontrado.group("valor").strip()
            inicio_cuerpo = j + 1
        cuerpo = "\n".join(lineas[inicio_cuerpo:]).strip()

        estado = meta.get("estado", "").lower()
        if estado not in ESTADOS_CRITERIO:
            errores.append(
                f"criterio {cid}: estado '{meta.get('estado', '')}' no válido "
                f"(usa {', '.join(ESTADOS_CRITERIO)})"
            )
        requiere = tuple(
            c.strip().strip("`") for c in (meta.get("requiere") or "").split("|") if c.strip()
        )
        for condicion in requiere:
            if not all(_CONDICION.match(parte.strip()) for parte in condicion.split("&")):
                errores.append(
                    f"criterio {cid}: condición '{condicion}' no válida "
                    "(usa tipoDeHecho o tipoDeHecho.campo=valor, separadas por |)"
                )
        fuerza = meta.get("fuerza", "").lower()
        if fuerza not in FUERZAS_CRITERIO:
            errores.append(
                f"criterio {cid}: fuerza '{meta.get('fuerza', '')}' no válida "
                f"(usa {', '.join(FUERZAS_CRITERIO)})"
            )
        if not meta.get("fuente"):
            errores.append(f"criterio {cid}: falta la fuente")
        if not cuerpo:
            errores.append(f"criterio {cid}: no tiene explicación")
        criterios.append(Criterio(
            id=cid,
            nombre=titulo.group("nombre").strip(),
            estado=estado,
            fuente=meta.get("fuente", ""),
            cuerpo=cuerpo,
            pendiente=meta.get("pendiente") or None,
            fuerza=fuerza or "indicio",
            requiere=requiere,
        ))
    return criterios


def parsear_skill(ruta: Path) -> Skill:
    """Lee y valida un archivo de skill. Lanza ``SkillInvalida`` con todos los
    errores encontrados (no solo el primero), para corregirlos de una vez."""
    contenido = ruta.read_bytes()
    texto = contenido.decode("utf-8").replace("\r\n", "\n")
    errores: list[str] = []

    cabecera = _FRONTMATTER.match(texto)
    if not cabecera:
        raise SkillInvalida(ruta, ["falta la cabecera YAML entre '---'"])
    try:
        meta = yaml.safe_load(cabecera.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillInvalida(ruta, [f"cabecera YAML inválida: {exc}"]) from exc
    if not isinstance(meta, dict):
        raise SkillInvalida(ruta, ["la cabecera YAML debe ser un diccionario"])

    for clave in ("id", "tipo", "titulo", "version", "estado"):
        if meta.get(clave) in (None, ""):
            errores.append(f"falta '{clave}' en la cabecera")
    tipo = str(meta.get("tipo", ""))
    if tipo and tipo not in TIPOS_SKILL:
        errores.append(f"tipo '{tipo}' no válido (usa {', '.join(TIPOS_SKILL)})")
    estado = str(meta.get("estado", ""))
    if estado and estado not in ESTADOS_SKILL:
        errores.append(f"estado '{estado}' no válido (usa {', '.join(ESTADOS_SKILL)})")
    try:
        version = int(meta.get("version", 0))
    except (TypeError, ValueError):
        errores.append("'version' debe ser un número entero")
        version = 0

    secciones = _partir_secciones(texto[cabecera.end():])
    criterios: list[Criterio] = []
    texto_criterios = next(
        (v for k, v in secciones.items()
         if normalizar_titulo(k) == normalizar_titulo(SECCION_CRITERIOS)),
        None,
    )
    if texto_criterios is not None:
        criterios = _parsear_criterios(texto_criterios, errores)
    ids = [c.id for c in criterios]
    for repetido in sorted({i for i in ids if ids.count(i) > 1}):
        errores.append(f"criterio {repetido} repetido en el archivo")

    def tiene(titulo: str) -> bool:
        return any(normalizar_titulo(k) == normalizar_titulo(titulo) for k in secciones)

    if tipo == "paso":
        if not meta.get("paso"):
            errores.append("una skill de paso necesita 'paso' en la cabecera")
        if not tiene(SECCION_INSTRUCCIONES):
            errores.append(f"una skill de paso necesita la sección '{SECCION_INSTRUCCIONES}'")
    if tipo == "base" and not tiene(SECCION_ROL):
        errores.append(f"una skill base necesita la sección '{SECCION_ROL}'")

    medio = str(meta["medio"]).strip() if meta.get("medio") else None
    codigos = _como_tupla(meta.get("codigos_tipo_reclamo"))
    clasificaciones = _como_tupla(meta.get("clasificaciones"))
    if tipo == "medio":
        if not medio:
            errores.append("una skill de medio necesita 'medio' en la cabecera")
        if not tiene(SECCION_LECTURA):
            errores.append(f"una skill de medio necesita la sección '{SECCION_LECTURA}'")
    if tipo == "tipo_reclamo":
        if not codigos and not clasificaciones:
            errores.append("una skill de tipo de reclamo necesita 'codigos_tipo_reclamo' o 'clasificaciones'")
        if not tiene(SECCION_METODO):
            errores.append(f"una skill de tipo de reclamo necesita la sección '{SECCION_METODO}'")

    if errores:
        raise SkillInvalida(ruta, errores)

    return Skill(
        id=str(meta["id"]).strip(),
        tipo=tipo,
        titulo=str(meta["titulo"]).strip(),
        version=version,
        estado=estado,
        ruta=str(ruta),
        # Sobre el texto normalizado: los saltos de línea de Windows/Linux no
        # deben cambiar la versión registrada de la skill.
        hash=hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12],
        secciones=secciones,
        criterios=tuple(criterios),
        medio=medio,
        paso=str(meta["paso"]).strip() if meta.get("paso") else None,
        codigos_tipo_reclamo=tuple(c.zfill(3) for c in codigos),
        clasificaciones=tuple(c.upper() for c in clasificaciones),
        actualizado=str(meta["actualizado"]) if meta.get("actualizado") else None,
        validado_por=str(meta["validado_por"]) if meta.get("validado_por") else None,
    )


def _prefijo_clasificacion(clasificacion: str) -> str:
    """"A1. CONSUMO MEDIDO" -> "A1"."""
    return re.split(r"[.\s]", clasificacion.strip(), maxsplit=1)[0].upper()


class SkillFileRepository:

    def __init__(
        self,
        directorio: str | Path = DIRECTORIO_SKILLS,
        directorio_reemplazos: str | Path | None = None,
    ):
        self.directorio = Path(directorio)
        self.directorio_reemplazos = Path(directorio_reemplazos) if directorio_reemplazos else None
        self._lock = threading.Lock()
        self._firma: tuple | None = None
        self._skills: dict[str, Skill] = {}
        self._errores: list[str] = []

    # ------------------------------------------------------------------ #
    # Carga
    # ------------------------------------------------------------------ #
    @staticmethod
    def _md_en(directorio: Path | None) -> dict[str, Path]:
        if directorio is None or not directorio.is_dir():
            return {}
        return {
            ruta.relative_to(directorio).as_posix(): ruta
            for sub in SUBCARPETAS
            for ruta in (directorio / sub).glob("*.md")
        }

    def _archivos(self) -> list[tuple[str, list[tuple[str, Path]]]]:
        """Por cada ruta relativa, las fuentes en orden de preferencia: primero
        el reemplazo de producción (si existe) y luego el del repositorio."""
        principales = self._md_en(self.directorio)
        reemplazos = self._md_en(self.directorio_reemplazos)
        archivos = []
        for relativa in sorted(set(principales) | set(reemplazos)):
            fuentes = []
            if relativa in reemplazos:
                fuentes.append(("reemplazo", reemplazos[relativa]))
            if relativa in principales:
                fuentes.append(("repositorio", principales[relativa]))
            archivos.append((relativa, fuentes))
        return archivos

    @staticmethod
    def _firma_actual(archivos) -> tuple:
        return tuple(
            (str(ruta), ruta.stat().st_mtime_ns, ruta.stat().st_size)
            for _, fuentes in archivos for _, ruta in fuentes
        )

    def _asegurar_cargadas(self) -> None:
        with self._lock:
            archivos = self._archivos()
            firma = self._firma_actual(archivos)
            if firma == self._firma:
                return
            self._cargar(archivos)
            self._firma = firma

    @staticmethod
    def _leer_primera_valida(relativa: str, fuentes, errores: list[str]) -> Skill | None:
        """Usa el reemplazo de producción; si tiene errores, cae al archivo del
        repositorio para que una edición mal hecha no deje a Yumi sin la skill."""
        for origen, ruta in fuentes:
            etiqueta = f"{relativa} ({origen})" if len(fuentes) > 1 or origen == "reemplazo" else relativa
            try:
                return parsear_skill(ruta)
            except SkillInvalida as exc:
                errores.extend(f"{etiqueta}: {e}" for e in exc.errores)
            except (OSError, UnicodeDecodeError) as exc:
                errores.append(f"{etiqueta}: no se pudo leer ({exc})")
        return None

    def _cargar(self, archivos) -> None:
        skills: dict[str, Skill] = {}
        errores: list[str] = []
        dueno_criterio: dict[str, str] = {}
        for relativa, fuentes in archivos:
            skill = self._leer_primera_valida(relativa, fuentes, errores)
            if skill is None:
                continue
            if skill.id in skills:
                errores.append(f"{relativa}: id '{skill.id}' ya usado por {Path(skills[skill.id].ruta).name}")
                continue
            choques = [c.id for c in skill.criterios if c.id in dueno_criterio]
            if choques:
                errores.extend(
                    f"{relativa}: criterio {cid} ya definido en {dueno_criterio[cid]}"
                    for cid in choques
                )
                continue
            for c in skill.criterios:
                dueno_criterio[c.id] = relativa
            skills[skill.id] = skill

        for error in errores:
            logger.error("[SKILLS] %s", error)
        reemplazadas = [s.id for s in skills.values()
                        if self.directorio_reemplazos
                        and Path(s.ruta).is_relative_to(self.directorio_reemplazos)]
        logger.info(
            "[SKILLS] %d skills cargadas desde %s (%d con errores; reemplazadas en producción: %s)",
            len(skills), self.directorio, len(errores), ", ".join(reemplazadas) or "ninguna",
        )
        self._skills = skills
        self._errores = errores

    # ------------------------------------------------------------------ #
    # Consulta
    # ------------------------------------------------------------------ #
    def todas(self) -> list[Skill]:
        self._asegurar_cargadas()
        return [s for s in self._skills.values() if s.estado != "inactivo"]

    def obtener(self, skill_id: str) -> Skill | None:
        return next((s for s in self.todas() if s.id == skill_id), None)

    def base(self) -> list[Skill]:
        """Skills base (rol y reglas comunes a todos los pasos), por id."""
        return sorted((s for s in self.todas() if s.tipo == "base"), key=lambda s: s.id)

    def para_paso(self, paso_id: str) -> Skill | None:
        return next(
            (s for s in self.todas() if s.tipo == "paso" and s.paso == paso_id), None,
        )

    def para_medio(self, medio_id: str) -> Skill | None:
        return next(
            (s for s in self.todas() if s.tipo == "medio" and s.medio == medio_id), None,
        )

    def para_tipo_reclamo(
        self, codigo: str | None = None, clasificacion: str | None = None,
    ) -> Skill | None:
        codigo_norm = codigo.strip().zfill(3) if codigo and codigo.strip() else None
        prefijo = _prefijo_clasificacion(clasificacion) if clasificacion and clasificacion.strip() else None
        for skill in self.todas():
            if skill.tipo != "tipo_reclamo":
                continue
            if codigo_norm and codigo_norm in skill.codigos_tipo_reclamo:
                return skill
            if prefijo and prefijo in skill.clasificaciones:
                return skill
        return None

    def errores(self) -> list[str]:
        self._asegurar_cargadas()
        return list(self._errores)


_repositorio: SkillFileRepository | None = None


def _directorio_reemplazos_configurado() -> Path | None:
    from app.src.infrastructure.config.settings import settings
    valor = settings.yumi_skills_path.strip()
    if valor.lower() == "desactivado":
        return None
    return Path(valor) if valor else DIRECTORIO_REEMPLAZOS


def repositorio_skills() -> SkillFileRepository:
    """Repositorio compartido del proceso (las skills se releen solas si cambian)."""
    global _repositorio
    if _repositorio is None:
        _repositorio = SkillFileRepository(DIRECTORIO_SKILLS, _directorio_reemplazos_configurado())
    return _repositorio


def _main() -> int:
    if len(sys.argv) > 1:
        repo = SkillFileRepository(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        repo = SkillFileRepository(DIRECTORIO_SKILLS, _directorio_reemplazos_configurado())
    print(f"Skills del repositorio: {repo.directorio}")
    print(f"Reemplazos de producción: {repo.directorio_reemplazos or '(desactivados)'}")
    skills = repo.todas()
    for skill in sorted(skills, key=lambda s: s.id):
        if repo.directorio_reemplazos and Path(skill.ruta).is_relative_to(repo.directorio_reemplazos):
            print(f"     (reemplazada desde {skill.ruta})")
        por_estado: dict[str, int] = {}
        for c in skill.criterios:
            por_estado[c.estado] = por_estado.get(c.estado, 0) + 1
        resumen = ", ".join(f"{n} {e}" for e, n in sorted(por_estado.items())) or "sin criterios"
        print(f"OK   {skill.version_completa:<45} [{skill.estado}] {resumen}")
        for c in skill.criterios:
            if c.pendiente:
                print(f"       pendiente {c.id}: {c.pendiente}")
    for error in repo.errores():
        print(f"ERROR {error}")
    return 1 if repo.errores() else 0


if __name__ == "__main__":
    sys.exit(_main())
