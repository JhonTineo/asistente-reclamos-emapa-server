"""Base normativa versionada (SQLite): la FUENTE DE VERDAD del texto de los
reglamentos. Qdrant, el índice de títulos y la búsqueda léxica se derivan de
aquí y se regeneran cuando algo cambia.

Modelo:
- normas: un reglamento ("RC" = Reglamento de Calidad, "RGR" = Reglamento
  General de Reclamos).
- unidades: artículo, numeral ("92.3") o literal ("91 f)") con un ID ESTABLE
  ("RC.92.3", "RC.91.f") que no cambia aunque cambie el texto. Las demás
  piezas del sistema (criterios, citas, mapa de hechos) apuntan a ese ID.
- versiones: el texto de una unidad en un periodo. Una modificación normativa
  cierra la versión vigente (vigente_hasta) y abre otra: solo cambia la unidad
  modificada y queda el historial (dispositivo que la modificó, nota original).

El texto de un artículo con numerales o literales es solo su parte introductoria;
el resto vive en sus unidades hijas. Así una modificación al 91 f) no duplica
ni desactualiza el texto del artículo 91 completo.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("adapters.sqlite_normativa")

MIGRACIONES: list[str] = [
    """
    CREATE TABLE normas (
        id           TEXT PRIMARY KEY,
        nombre       TEXT NOT NULL,
        resolucion   TEXT,
        archivo      TEXT,
        coleccion    TEXT,
        orden        INTEGER NOT NULL DEFAULT 0,
        creado_en    TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE unidades (
        id           TEXT PRIMARY KEY,
        norma_id     TEXT NOT NULL REFERENCES normas(id) ON DELETE CASCADE,
        tipo         TEXT NOT NULL,            -- articulo | numeral | literal | anexo | cuadro
        articulo     TEXT NOT NULL,            -- "91"
        numeral      TEXT,                     -- "92.3" | "91 f)" | NULL (artículo)
        padre_id     TEXT REFERENCES unidades(id),
        orden        INTEGER NOT NULL,
        titulo       TEXT,                     -- título del artículo ("Determinación del Volumen ...")
        ruta         TEXT                      -- "TÍTULO V ... > CAPÍTULO II ..."
    );
    CREATE INDEX ix_unidades_norma ON unidades(norma_id, orden);

    CREATE TABLE versiones (
        id              INTEGER PRIMARY KEY,
        unidad_id       TEXT NOT NULL REFERENCES unidades(id) ON DELETE CASCADE,
        texto           TEXT NOT NULL,
        vigente_desde   TEXT,                  -- NULL = desconocida (carga inicial)
        vigente_hasta   TEXT,                  -- NULL = sigue vigente
        estado          TEXT NOT NULL DEFAULT 'vigente',   -- vigente | derogado | reemplazado
        dispositivos    TEXT NOT NULL DEFAULT '[]',        -- ["RCD 058-2023-SUNASS-CD", ...]
        nota            TEXT,                  -- nota de vigencia original del PDF
        origen          TEXT NOT NULL,         -- importacion_pdf | edicion_manual | modificatoria
        creado_por      TEXT,
        creado_en       TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX ix_versiones_unidad ON versiones(unidad_id, estado);
    """,
]


@dataclass
class UnidadNormativa:
    """Una unidad con su versión (la vigente, o la vigente a una fecha)."""
    id: str
    norma_id: str
    norma: str
    coleccion: str | None
    tipo: str
    articulo: str
    numeral: str | None
    padre_id: str | None
    orden: int
    titulo: str | None
    ruta: str | None
    texto: str
    version_id: int
    vigente_desde: str | None
    vigente_hasta: str | None
    estado: str
    dispositivos: list[str] = field(default_factory=list)
    nota: str | None = None


_SELECT = """
    SELECT u.id, u.norma_id, n.nombre AS norma, n.coleccion, u.tipo, u.articulo,
           u.numeral, u.padre_id, u.orden, u.titulo, u.ruta,
           v.texto, v.id AS version_id, v.vigente_desde, v.vigente_hasta,
           v.estado, v.dispositivos, v.nota
    FROM unidades u
    JOIN normas n ON n.id = u.norma_id
    JOIN versiones v ON v.unidad_id = u.id
"""


def _filtro_vigencia(fecha: str | None) -> tuple[str, list]:
    """Versión vigente hoy (estado='vigente') o la que regía en `fecha`
    (YYYY-MM-DD). Las versiones de la carga inicial no tienen vigente_desde:
    se asume que rigen desde siempre."""
    if fecha is None:
        return "v.estado = 'vigente'", []
    return ("(v.vigente_desde IS NULL OR v.vigente_desde <= ?) "
            "AND (v.vigente_hasta IS NULL OR v.vigente_hasta > ?) "
            "AND v.estado != 'derogado'"), [fecha, fecha]


def _a_unidad(fila: sqlite3.Row) -> UnidadNormativa:
    datos = dict(fila)
    datos["dispositivos"] = json.loads(datos.get("dispositivos") or "[]")
    return UnidadNormativa(**datos)


class SqliteNormativaRepository:

    def __init__(self, ruta: str | Path):
        self.ruta = str(ruta)
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.ruta, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        if self.ruta != ":memory:":
            self._con.execute("PRAGMA journal_mode = WAL")
        self._con.execute("PRAGMA busy_timeout = 5000")
        self._migrar()

    def _migrar(self) -> None:
        with self._lock:
            version = self._con.execute("PRAGMA user_version").fetchone()[0]
            for numero, script in enumerate(MIGRACIONES, start=1):
                if version < numero:
                    self._con.executescript(
                        f"BEGIN;\n{script}\nPRAGMA user_version = {numero};\nCOMMIT;"
                    )
                    logger.info("[NORMATIVA] Migración %d aplicada en %s", numero, self.ruta)

    @contextmanager
    def _tx(self):
        with self._lock:
            cur = self._con.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            cur.execute("COMMIT")

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------ #
    # Escritura
    # ------------------------------------------------------------------ #
    def importar_norma(self, norma: dict, unidades: list[dict]) -> int:
        """Carga (o recarga) una norma completa en una sola transacción.
        `unidades`: dicts con id, tipo, articulo, numeral, padre_id, orden,
        titulo, ruta, texto, dispositivos, nota. Borra lo que hubiera de esa
        norma: es la carga inicial desde el PDF consolidado, no una modificación
        (para eso, `nueva_version`)."""
        with self._tx() as cur:
            cur.execute("DELETE FROM normas WHERE id = ?", (norma["id"],))
            cur.execute(
                "INSERT INTO normas (id, nombre, resolucion, archivo, coleccion, orden) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (norma["id"], norma["nombre"], norma.get("resolucion"), norma.get("archivo"),
                 norma.get("coleccion"), norma.get("orden", 0)),
            )
            for u in unidades:
                cur.execute(
                    "INSERT INTO unidades (id, norma_id, tipo, articulo, numeral, padre_id, orden, titulo, ruta) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (u["id"], norma["id"], u["tipo"], u["articulo"], u.get("numeral"),
                     u.get("padre_id"), u["orden"], u.get("titulo"), u.get("ruta")),
                )
                cur.execute(
                    "INSERT INTO versiones (unidad_id, texto, dispositivos, nota, origen) "
                    "VALUES (?, ?, ?, ?, 'importacion_pdf')",
                    (u["id"], u["texto"], json.dumps(u.get("dispositivos") or [], ensure_ascii=False),
                     u.get("nota")),
                )
        return len(unidades)

    def nueva_version(self, unidad_id: str, texto: str, *, vigente_desde: str | None,
                      dispositivos: list[str] | None = None, nota: str | None = None,
                      origen: str = "edicion_manual", creado_por: str | None = None) -> int:
        """Modifica UNA unidad: cierra su versión vigente y abre otra. Las demás
        unidades de la norma no se tocan."""
        with self._tx() as cur:
            if not cur.execute("SELECT 1 FROM unidades WHERE id = ?", (unidad_id,)).fetchone():
                raise KeyError(f"No existe la unidad normativa {unidad_id}")
            cur.execute(
                "UPDATE versiones SET estado = 'reemplazado', vigente_hasta = ? "
                "WHERE unidad_id = ? AND estado = 'vigente'",
                (vigente_desde, unidad_id),
            )
            cur.execute(
                "INSERT INTO versiones (unidad_id, texto, vigente_desde, dispositivos, nota, origen, creado_por) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (unidad_id, texto, vigente_desde, json.dumps(dispositivos or [], ensure_ascii=False),
                 nota, origen, creado_por),
            )
            return cur.lastrowid

    # ------------------------------------------------------------------ #
    # Lectura
    # ------------------------------------------------------------------ #
    def normas(self) -> list[dict]:
        with self._lock:
            filas = self._con.execute("SELECT * FROM normas ORDER BY orden, id").fetchall()
        return [dict(f) for f in filas]

    def unidades(self, norma_id: str | None = None, fecha: str | None = None) -> list[UnidadNormativa]:
        """Unidades con su versión vigente (o la vigente a `fecha`), en orden
        del documento."""
        filtro, params = _filtro_vigencia(fecha)
        sql = f"{_SELECT} WHERE {filtro}"
        if norma_id:
            sql += " AND u.norma_id = ?"
            params.append(norma_id)
        sql += " ORDER BY (SELECT orden FROM normas WHERE id = u.norma_id), u.norma_id, u.orden"
        with self._lock:
            filas = self._con.execute(sql, params).fetchall()
        return [_a_unidad(f) for f in filas]

    def unidad(self, unidad_id: str, fecha: str | None = None) -> UnidadNormativa | None:
        filtro, params = _filtro_vigencia(fecha)
        with self._lock:
            fila = self._con.execute(
                f"{_SELECT} WHERE u.id = ? AND {filtro} ORDER BY v.id DESC LIMIT 1",
                [unidad_id, *params],
            ).fetchone()
        return _a_unidad(fila) if fila else None

    def historial(self, unidad_id: str) -> list[dict]:
        with self._lock:
            filas = self._con.execute(
                "SELECT id, texto, vigente_desde, vigente_hasta, estado, dispositivos, nota, "
                "origen, creado_por, creado_en FROM versiones WHERE unidad_id = ? ORDER BY id",
                (unidad_id,),
            ).fetchall()
        salida = []
        for f in filas:
            d = dict(f)
            d["dispositivos"] = json.loads(d["dispositivos"] or "[]")
            salida.append(d)
        return salida

    def esta_vacia(self) -> bool:
        with self._lock:
            return self._con.execute("SELECT COUNT(*) FROM normas").fetchone()[0] == 0
