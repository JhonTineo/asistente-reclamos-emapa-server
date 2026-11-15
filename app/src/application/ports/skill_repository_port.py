"""Puerto de acceso a las skills (conocimiento del oficio de Yumi)."""

from typing import Protocol

from app.src.core.model.skill import Skill


class PuertoRepositorioSkills(Protocol):

    def todas(self) -> list[Skill]:
        """Skills válidas y no inactivas."""
        ...

    def obtener(self, skill_id: str) -> Skill | None:
        ...

    def base(self) -> list[Skill]:
        """Skills base: rol de Yumi y reglas comunes a todos los pasos."""
        ...

    def para_medio(self, medio_id: str) -> Skill | None:
        ...

    def para_paso(self, paso_id: str) -> Skill | None:
        """Skill con las instrucciones de un paso del workflow."""
        ...

    def para_tipo_reclamo(
        self, codigo: str | None = None, clasificacion: str | None = None,
    ) -> Skill | None:
        """Skill del tipo de reclamo, por código ("001") o por clasificación
        ("A1. CONSUMO MEDIDO")."""
        ...

    def errores(self) -> list[str]:
        """Problemas encontrados al cargar los archivos (las skills con
        errores no se cargan)."""
        ...
