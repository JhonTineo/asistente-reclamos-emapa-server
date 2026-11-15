"""Memoria del caso persistente en SQLite.

Guarda cada InformeAtencion en curso repartido en tablas: el caso, sus
objetivos, los datos crudos de cada medio, el registro de hechos, los
artefactos con versiones y las decisiones. ``guardar`` sincroniza el estado
completo y es idempotente: un artefacto solo crea versión nueva si su contenido
cambió, y un hecho que deja de aparecer se marca ``reemplazado`` (no se borra).

Usa una sola conexión protegida por un lock: la app corre en un solo proceso
uvicorn y los medios que se analizan en paralelo escriben desde el threadpool.
"""

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from app.src.application.services.informe.artefactos import (
    ORIGEN_GENERADO, artefactos_actuales, firma, origen_de, tipo_resumen,
)
from app.src.core.model.conciliacion import Conciliacion
from app.src.core.model.informe_atencion import (
    BloqueMedio, InformeAtencion, MotivoEvaluacion, ObjetivoInvestigacion,
    ProblemaNormado,
)
from app.src.core.model.reclamo import Reclamo

logger = logging.getLogger("adapters.sqlite_casos")

ESTADO_ABIERTO = "en_atencion"
ESTADO_FINALIZADO = "finalizado"

# Cada entrada es una migración; el índice + 1 es su número de versión
# (PRAGMA user_version). Nunca se edita una migración ya publicada: los cambios
# de esquema se agregan como una entrada nueva al final.
MIGRACIONES: list[str] = [
    """
    CREATE TABLE casos (
        id                  INTEGER PRIMARY KEY,
        codreclamo          TEXT NOT NULL,
        suministro          TEXT NOT NULL,
        numero              TEXT,
        fecha               TEXT,
        asunto              TEXT,
        destinatario        TEXT,
        clasificacion       TEXT,
        datos_reclamo       TEXT,
        medios_probatorios  TEXT NOT NULL DEFAULT '[]',
        ventana_meses       TEXT NOT NULL DEFAULT '[]',
        documento_tecnico   TEXT,
        informe_original    TEXT,
        secuencia_hechos    TEXT NOT NULL DEFAULT '{}',
        estado              TEXT NOT NULL DEFAULT 'en_atencion',
        sesion_id           TEXT,
        creado_por          TEXT,
        creado_en           TEXT NOT NULL DEFAULT (datetime('now')),
        actualizado_en      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX ux_caso_abierto ON casos(codreclamo) WHERE estado = 'en_atencion';

    CREATE TABLE objetivos (
        caso_id       INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
        numero        INTEGER NOT NULL,
        descripcion   TEXT NOT NULL,
        medio         TEXT,
        determinante  INTEGER NOT NULL DEFAULT 0,
        resultado     TEXT,
        evidencia     TEXT,
        origen        TEXT NOT NULL DEFAULT 'generado',
        PRIMARY KEY (caso_id, numero)
    );

    CREATE TABLE medios_consultados (
        caso_id        INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
        medio_id       TEXT NOT NULL,
        medio_nombre   TEXT NOT NULL,
        orden          INTEGER NOT NULL DEFAULT 0,
        estado         TEXT NOT NULL DEFAULT 'ok',
        error          TEXT,
        entidad        TEXT,
        consultado_en  TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (caso_id, medio_id)
    );

    CREATE TABLE hechos (
        caso_id        INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
        id             TEXT NOT NULL,
        medio_id       TEXT NOT NULL,
        orden          INTEGER NOT NULL DEFAULT 0,
        tipo           TEXT NOT NULL,
        periodo        TEXT,
        enunciado      TEXT NOT NULL,
        valor          TEXT,
        origen         TEXT NOT NULL,
        confianza      TEXT NOT NULL,
        estado         TEXT NOT NULL DEFAULT 'vigente',
        reemplaza      TEXT,
        fuente         TEXT,
        texto_original TEXT,
        responsable    TEXT,
        accion         TEXT,
        base_legal     TEXT,
        seleccionado   INTEGER NOT NULL DEFAULT 0,
        creado_en      TEXT NOT NULL DEFAULT (datetime('now')),
        actualizado_en TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (caso_id, id)
    );
    CREATE INDEX ix_hechos_medio ON hechos(caso_id, medio_id, estado);

    CREATE TABLE hecho_normativa (
        caso_id    INTEGER NOT NULL,
        hecho_id   TEXT NOT NULL,
        orden      INTEGER NOT NULL,
        articulo   TEXT,
        numeral    TEXT,
        score      REAL,
        texto      TEXT,
        PRIMARY KEY (caso_id, hecho_id, orden),
        FOREIGN KEY (caso_id, hecho_id) REFERENCES hechos(caso_id, id) ON DELETE CASCADE
    );

    CREATE TABLE artefactos (
        id             INTEGER PRIMARY KEY,
        caso_id        INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
        tipo           TEXT NOT NULL,
        version        INTEGER NOT NULL,
        texto          TEXT NOT NULL,
        datos          TEXT,
        origen         TEXT NOT NULL,
        skill          TEXT,
        skill_version  TEXT,
        modelo         TEXT,
        vigente        INTEGER NOT NULL DEFAULT 1,
        creado_por     TEXT,
        creado_en      TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE (caso_id, tipo, version)
    );
    CREATE UNIQUE INDEX ux_artefacto_vigente ON artefactos(caso_id, tipo) WHERE vigente = 1;

    CREATE TABLE artefacto_hechos (
        artefacto_id  INTEGER NOT NULL REFERENCES artefactos(id) ON DELETE CASCADE,
        caso_id       INTEGER NOT NULL,
        hecho_id      TEXT NOT NULL,
        PRIMARY KEY (artefacto_id, hecho_id),
        FOREIGN KEY (caso_id, hecho_id) REFERENCES hechos(caso_id, id) ON DELETE CASCADE
    );

    CREATE TABLE decisiones (
        id                       INTEGER PRIMARY KEY,
        caso_id                  INTEGER NOT NULL REFERENCES casos(id) ON DELETE CASCADE,
        veredicto                TEXT,
        estado_evaluacion        TEXT NOT NULL,
        motivos                  TEXT NOT NULL DEFAULT '[]',
        mensaje                  TEXT,
        origen                   TEXT,
        conclusion_artefacto_id  INTEGER REFERENCES artefactos(id) ON DELETE SET NULL,
        detalle                  TEXT,
        vigente                  INTEGER NOT NULL DEFAULT 1,
        creado_en                TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE UNIQUE INDEX ux_decision_vigente ON decisiones(caso_id) WHERE vigente = 1;

    CREATE TABLE llamadas_llm (
        id             INTEGER PRIMARY KEY,
        caso_id        INTEGER REFERENCES casos(id) ON DELETE CASCADE,
        paso           TEXT NOT NULL,
        skill          TEXT,
        skill_version  TEXT,
        modelo         TEXT,
        capas          TEXT,
        system         TEXT,
        usuario        TEXT,
        respuesta      TEXT,
        duracion_ms    INTEGER,
        error          TEXT,
        creado_en      TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
    # 2: constataciones (hechos neutros o favorables) en el mismo registro.
    """
    ALTER TABLE hechos ADD COLUMN clase TEXT NOT NULL DEFAULT 'problema';
    """,
    # 3: qué proveedor respondió cada llamada ("modelo" guarda el modelo real,
    # no el "auto" pedido).
    """
    ALTER TABLE llamadas_llm ADD COLUMN proveedor TEXT;
    """,
]


def _json_default(valor):
    # numpy/pandas exponen .item() para obtener el escalar nativo de Python.
    if hasattr(valor, "item"):
        try:
            return valor.item()
        except (TypeError, ValueError):
            pass
    if isinstance(valor, datetime):
        return valor.isoformat()
    return str(valor)


def _dumps(valor) -> str | None:
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=_json_default)


def _loads(texto: str | None, por_defecto=None):
    if texto is None:
        return por_defecto
    return json.loads(texto)


def _construir(cls, datos: dict | None):
    """Instancia un dataclass ignorando claves que ya no existen en él (por si
    el modelo cambió desde que se guardó el registro)."""
    if datos is None:
        return None
    nombres = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in datos.items() if k in nombres})


def _confianza(problema: ProblemaNormado) -> str:
    # Un problema con cita literal viene de texto libre (observaciones del
    # inspector); el resto se calcula sobre datos estructurados.
    return "observacion" if problema.texto_original else "dato"


def _en(columna: str, valores: list) -> tuple[str, list]:
    """Fragmento ``columna NOT IN (...)`` seguro también para listas vacías."""
    if not valores:
        return "1 = 1", []
    return f"{columna} NOT IN ({', '.join('?' for _ in valores)})", list(valores)


class SqliteCasoRepository:

    def __init__(self, ruta: str | Path):
        self.ruta = str(ruta)
        if self.ruta != ":memory:":
            Path(self.ruta).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.ruta, check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA journal_mode = WAL")
        self._con.execute("PRAGMA busy_timeout = 5000")
        self._migrar()

    # ------------------------------------------------------------------ #
    # Infraestructura
    # ------------------------------------------------------------------ #
    def _migrar(self) -> None:
        with self._lock:
            version = self._con.execute("PRAGMA user_version").fetchone()[0]
            for numero, script in enumerate(MIGRACIONES, start=1):
                if version < numero:
                    self._con.executescript(
                        f"BEGIN;\n{script}\nPRAGMA user_version = {numero};\nCOMMIT;"
                    )
                    logger.info("[SQLITE] Migración %d aplicada en %s", numero, self.ruta)

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
            else:
                cur.execute("COMMIT")

    def cerrar_conexion(self) -> None:
        with self._lock:
            self._con.close()

    # ------------------------------------------------------------------ #
    # Escritura
    # ------------------------------------------------------------------ #
    def guardar(self, informe: InformeAtencion) -> None:
        with self._tx() as cur:
            caso_id = self._guardar_caso(cur, informe)
            self._guardar_objetivos(cur, caso_id, informe)
            self._guardar_medios(cur, caso_id, informe)
            self._guardar_hechos(cur, caso_id, informe)
            self._guardar_artefactos(cur, caso_id, informe)
            self._guardar_decisiones(cur, caso_id, informe)

    def _guardar_caso(self, cur, informe: InformeAtencion) -> int:
        valores = {
            "suministro": informe.suministro,
            "numero": informe.numero,
            "fecha": informe.fecha.isoformat() if informe.fecha else None,
            "asunto": informe.asunto,
            "destinatario": informe.destinatario,
            "clasificacion": informe.clasificacion,
            "datos_reclamo": _dumps(asdict(informe.datos_reclamo)) if informe.datos_reclamo else None,
            "medios_probatorios": _dumps(informe.medios_probatorios or []),
            "ventana_meses": _dumps([list(v) for v in informe.ventana_meses]),
            "documento_tecnico": _dumps(informe.documento_tecnico_operacional),
            "informe_original": informe.informe_texto_original,
            "secuencia_hechos": _dumps(informe.secuencia_hechos or {}),
            "sesion_id": informe.sesion_id,
            "creado_por": informe.creado_por,
        }
        fila = cur.execute(
            "SELECT id FROM casos WHERE codreclamo = ? AND estado = ?",
            (informe.reclamo, ESTADO_ABIERTO),
        ).fetchone()
        if fila:
            asignaciones = ", ".join(f"{k} = ?" for k in valores)
            cur.execute(
                f"UPDATE casos SET {asignaciones}, actualizado_en = datetime('now') WHERE id = ?",
                (*valores.values(), fila["id"]),
            )
            return fila["id"]
        columnas = ", ".join(["codreclamo", *valores])
        marcas = ", ".join("?" for _ in range(len(valores) + 1))
        cur.execute(
            f"INSERT INTO casos ({columnas}) VALUES ({marcas})",
            (informe.reclamo, *valores.values()),
        )
        return cur.lastrowid

    @staticmethod
    def _guardar_objetivos(cur, caso_id: int, informe: InformeAtencion) -> None:
        cur.execute("DELETE FROM objetivos WHERE caso_id = ?", (caso_id,))
        cur.executemany(
            "INSERT INTO objetivos (caso_id, numero, descripcion, medio, determinante, "
            "resultado, evidencia) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (caso_id, o.id, o.descripcion, o.medio, int(o.determinante),
                 o.resultado, o.evidencia)
                for o in informe.objetivos
            ],
        )

    @staticmethod
    def _guardar_medios(cur, caso_id: int, informe: InformeAtencion) -> None:
        for orden, bloque in enumerate(informe.bloques):
            cur.execute(
                """
                INSERT INTO medios_consultados (caso_id, medio_id, medio_nombre, orden, entidad)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (caso_id, medio_id) DO UPDATE SET
                    medio_nombre = excluded.medio_nombre,
                    orden = excluded.orden,
                    consultado_en = CASE
                        WHEN medios_consultados.entidad IS excluded.entidad
                        THEN medios_consultados.consultado_en
                        ELSE datetime('now') END,
                    entidad = excluded.entidad
                """,
                (caso_id, bloque.medio_id, bloque.medio_nombre, orden, _dumps(bloque.entidad)),
            )
        condicion, params = _en("medio_id", [b.medio_id for b in informe.bloques])
        cur.execute(
            f"DELETE FROM medios_consultados WHERE caso_id = ? AND {condicion}",
            (caso_id, *params),
        )

    @staticmethod
    def _guardar_hechos(cur, caso_id: int, informe: InformeAtencion) -> None:
        presentes: list[str] = []
        for bloque in informe.bloques:
            for orden, p in enumerate(bloque.hechos):
                if not p.id:
                    logger.warning(
                        "[SQLITE] Problema sin ID en %s/%s; no se persiste como hecho",
                        informe.reclamo, bloque.medio_id,
                    )
                    continue
                presentes.append(p.id)
                cur.execute(
                    """
                    INSERT INTO hechos (caso_id, id, medio_id, orden, clase, tipo, periodo,
                        enunciado, valor, origen, confianza, estado, fuente, texto_original,
                        responsable, accion, base_legal, seleccionado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'regla', ?, 'vigente', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (caso_id, id) DO UPDATE SET
                        medio_id = excluded.medio_id,
                        orden = excluded.orden,
                        clase = excluded.clase,
                        tipo = excluded.tipo,
                        periodo = excluded.periodo,
                        valor = excluded.valor,
                        enunciado = excluded.enunciado,
                        confianza = excluded.confianza,
                        estado = 'vigente',
                        fuente = excluded.fuente,
                        texto_original = excluded.texto_original,
                        responsable = excluded.responsable,
                        accion = excluded.accion,
                        base_legal = excluded.base_legal,
                        seleccionado = excluded.seleccionado,
                        actualizado_en = datetime('now')
                    """,
                    (caso_id, p.id, bloque.medio_id, orden, p.clase, p.tipo, p.periodo,
                     p.detalle, _dumps(p.valor), _confianza(p), p.fuente,
                     p.texto_original, p.responsable,
                     p.accion, p.base_legal, int(p.seleccionado)),
                )
                cur.execute(
                    "DELETE FROM hecho_normativa WHERE caso_id = ? AND hecho_id = ?",
                    (caso_id, p.id),
                )
                cur.executemany(
                    "INSERT INTO hecho_normativa (caso_id, hecho_id, orden, articulo, "
                    "numeral, score, texto) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (caso_id, p.id, i, _dumps(a.get("article")),
                         _dumps(a.get("numeral")), a.get("score"), a.get("texto"))
                        for i, a in enumerate(p.articulos or [])
                    ],
                )
        condicion, params = _en("id", presentes)
        cur.execute(
            f"UPDATE hechos SET estado = 'reemplazado', actualizado_en = datetime('now') "
            f"WHERE caso_id = ? AND estado = 'vigente' AND {condicion}",
            (caso_id, *params),
        )

    @staticmethod
    def _guardar_artefactos(cur, caso_id: int, informe: InformeAtencion) -> None:
        actuales = artefactos_actuales(informe)
        for tipo, (texto, datos) in actuales.items():
            datos_json = _dumps(datos)
            origen = origen_de(informe, tipo, texto, datos)
            vigente = cur.execute(
                "SELECT id, texto, datos, origen FROM artefactos "
                "WHERE caso_id = ? AND tipo = ? AND vigente = 1",
                (caso_id, tipo),
            ).fetchone()
            if vigente and vigente["texto"] == texto and vigente["datos"] == datos_json:
                if vigente["origen"] != origen:
                    cur.execute(
                        "UPDATE artefactos SET origen = ? WHERE id = ?", (origen, vigente["id"]),
                    )
                continue
            if vigente:
                cur.execute("UPDATE artefactos SET vigente = 0 WHERE id = ?", (vigente["id"],))
            version = cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM artefactos WHERE caso_id = ? AND tipo = ?",
                (caso_id, tipo),
            ).fetchone()[0]
            cur.execute(
                "INSERT INTO artefactos (caso_id, tipo, version, texto, datos, origen, creado_por) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (caso_id, tipo, version, texto, datos_json, origen,
                 informe.creado_por if origen != ORIGEN_GENERADO else None),
            )
            if tipo == "dictamen":
                SqliteCasoRepository._citar_hechos(cur, caso_id, cur.lastrowid, datos)
        # Un artefacto que desapareció del informe (p.ej. la conclusión se
        # invalidó) deja de estar vigente, pero su historial se conserva.
        condicion, params = _en("tipo", list(actuales))
        cur.execute(
            f"UPDATE artefactos SET vigente = 0 WHERE caso_id = ? AND vigente = 1 AND {condicion}",
            (caso_id, *params),
        )

    @staticmethod
    def _citar_hechos(cur, caso_id: int, artefacto_id: int, dictamen: dict | None) -> None:
        """Registra en artefacto_hechos los hechos de medios que cita el
        dictamen (los hechos H-caso-NN se recalculan y viven en el propio
        dictamen). Es lo que permite saber qué dictamen rehacer si un hecho cambia."""
        citados = sorted({
            h for f in (dictamen or {}).get("factores") or []
            if f.get("aplica") == "aplica" for h in f.get("hechos") or []
        })
        if not citados:
            return
        marcas = ", ".join("?" for _ in citados)
        existentes = [fila[0] for fila in cur.execute(
            f"SELECT id FROM hechos WHERE caso_id = ? AND id IN ({marcas})", (caso_id, *citados),
        )]
        cur.executemany(
            "INSERT OR IGNORE INTO artefacto_hechos (artefacto_id, caso_id, hecho_id) VALUES (?, ?, ?)",
            [(artefacto_id, caso_id, h) for h in existentes],
        )

    @staticmethod
    def _guardar_decisiones(cur, caso_id: int, informe: InformeAtencion) -> None:
        conclusion = cur.execute(
            "SELECT id FROM artefactos WHERE caso_id = ? AND tipo = 'conclusion' AND vigente = 1",
            (caso_id,),
        ).fetchone()
        valores = (
            informe.veredicto,
            informe.estado_evaluacion,
            _dumps([asdict(m) for m in informe.motivos_evaluacion]),
            informe.mensaje_evaluacion,
            informe.origen_decision,
            conclusion["id"] if conclusion else None,
        )
        vigente = cur.execute(
            "SELECT id FROM decisiones WHERE caso_id = ? AND vigente = 1", (caso_id,),
        ).fetchone()
        if vigente:
            cur.execute(
                "UPDATE decisiones SET veredicto = ?, estado_evaluacion = ?, motivos = ?, "
                "mensaje = ?, origen = ?, conclusion_artefacto_id = ? WHERE id = ?",
                (*valores, vigente["id"]),
            )
        else:
            cur.execute(
                "INSERT INTO decisiones (caso_id, veredicto, estado_evaluacion, motivos, "
                "mensaje, origen, conclusion_artefacto_id, vigente) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (caso_id, *valores),
            )

        # El historial en memoria solo crece: se insertan las entradas nuevas.
        guardadas = cur.execute(
            "SELECT COUNT(*) FROM decisiones WHERE caso_id = ? AND vigente = 0", (caso_id,),
        ).fetchone()[0]
        for entrada in informe.historial_decisiones[guardadas:]:
            cur.execute(
                "INSERT INTO decisiones (caso_id, veredicto, estado_evaluacion, mensaje, "
                "origen, detalle, vigente, creado_en) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                (caso_id, entrada.get("veredicto"),
                 entrada.get("estado_evaluacion") or "pendiente",
                 entrada.get("invalidada_por"), entrada.get("origen_decision"),
                 _dumps(entrada), entrada.get("fecha") or datetime.now().isoformat()),
            )

    def registrar_llamada(
        self,
        *,
        codreclamo: str | None,
        paso: str,
        skill: str | None,
        skill_version: str | None,
        modelo: str | None,
        capas: dict,
        system: str,
        usuario: str,
        respuesta: str | None,
        duracion_ms: int,
        error: str | None,
        proveedor: str | None = None,
    ) -> None:
        """Guarda qué contexto recibió el modelo y qué respondió. Se asocia a la
        atención abierta del reclamo; si no hay una (p.ej. el caso aún no se
        guardó), la llamada se registra sin caso."""
        with self._tx() as cur:
            caso = cur.execute(
                "SELECT id FROM casos WHERE codreclamo = ? AND estado = ?",
                (codreclamo, ESTADO_ABIERTO),
            ).fetchone() if codreclamo else None
            cur.execute(
                "INSERT INTO llamadas_llm (caso_id, paso, skill, skill_version, modelo, proveedor, "
                "capas, system, usuario, respuesta, duracion_ms, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (caso["id"] if caso else None, paso, skill, skill_version, modelo, proveedor,
                 _dumps(capas), system, usuario, respuesta, duracion_ms, error),
            )

    def cerrar(self, codreclamo: str, descartar: bool = False) -> None:
        with self._tx() as cur:
            if descartar:
                cur.execute(
                    "DELETE FROM casos WHERE codreclamo = ? AND estado = ?",
                    (codreclamo, ESTADO_ABIERTO),
                )
            else:
                cur.execute(
                    "UPDATE casos SET estado = ?, actualizado_en = datetime('now') "
                    "WHERE codreclamo = ? AND estado = ?",
                    (ESTADO_FINALIZADO, codreclamo, ESTADO_ABIERTO),
                )

    # ------------------------------------------------------------------ #
    # Lectura
    # ------------------------------------------------------------------ #
    def cargar_abiertos(self) -> list[InformeAtencion]:
        with self._lock:
            casos = self._con.execute(
                "SELECT * FROM casos WHERE estado = ? ORDER BY id", (ESTADO_ABIERTO,),
            ).fetchall()
            return [self._cargar_caso(c) for c in casos]

    def _cargar_caso(self, caso: sqlite3.Row) -> InformeAtencion:
        con = self._con
        caso_id = caso["id"]
        artefactos = {
            a["tipo"]: a for a in con.execute(
                "SELECT tipo, texto, datos, origen FROM artefactos WHERE caso_id = ? AND vigente = 1",
                (caso_id,),
            )
        }

        def texto(tipo: str) -> str | None:
            fila = artefactos.get(tipo)
            return fila["texto"] if fila else None

        objetivos = [
            ObjetivoInvestigacion(
                id=o["numero"], descripcion=o["descripcion"], medio=o["medio"],
                determinante=bool(o["determinante"]), resultado=o["resultado"],
                evidencia=o["evidencia"],
            )
            for o in con.execute(
                "SELECT * FROM objetivos WHERE caso_id = ? ORDER BY numero", (caso_id,),
            )
        ]

        articulos: dict[str, list[dict]] = {}
        for a in con.execute(
            "SELECT * FROM hecho_normativa WHERE caso_id = ? ORDER BY hecho_id, orden", (caso_id,),
        ):
            articulos.setdefault(a["hecho_id"], []).append({
                "article": _loads(a["articulo"]), "numeral": _loads(a["numeral"]),
                "score": a["score"], "texto": a["texto"],
            })

        problemas: dict[str, list[ProblemaNormado]] = {}
        constataciones: dict[str, list[ProblemaNormado]] = {}
        for h in con.execute(
            "SELECT * FROM hechos WHERE caso_id = ? AND estado = 'vigente' ORDER BY medio_id, orden",
            (caso_id,),
        ):
            destino = constataciones if h["clase"] == "constatacion" else problemas
            destino.setdefault(h["medio_id"], []).append(ProblemaNormado(
                tipo=h["tipo"], detalle=h["enunciado"], fuente=h["fuente"],
                texto_original=h["texto_original"], seleccionado=bool(h["seleccionado"]),
                articulos=articulos.get(h["id"], []), accion=h["accion"],
                responsable=h["responsable"], base_legal=h["base_legal"], id=h["id"],
                clase=h["clase"], periodo=h["periodo"], valor=_loads(h["valor"]),
            ))

        bloques = [
            BloqueMedio(
                medio_id=m["medio_id"], medio_nombre=m["medio_nombre"],
                entidad=_loads(m["entidad"], {}),
                resumen=texto(tipo_resumen(m["medio_id"])) or "",
                problemas=problemas.get(m["medio_id"], []),
                constataciones=constataciones.get(m["medio_id"], []),
            )
            for m in con.execute(
                "SELECT * FROM medios_consultados WHERE caso_id = ? ORDER BY orden", (caso_id,),
            )
        ]

        decision = con.execute(
            "SELECT * FROM decisiones WHERE caso_id = ? AND vigente = 1", (caso_id,),
        ).fetchone()
        historial = [
            _loads(d["detalle"], {})
            for d in con.execute(
                "SELECT detalle FROM decisiones WHERE caso_id = ? AND vigente = 0 ORDER BY id",
                (caso_id,),
            )
        ]

        conciliacion_fila = artefactos.get("conciliacion")
        conciliacion = (
            _construir(Conciliacion, _loads(conciliacion_fila["datos"], {}))
            if conciliacion_fila else None
        )

        informe = InformeAtencion(
            numero=caso["numero"],
            fecha=datetime.fromisoformat(caso["fecha"]) if caso["fecha"] else datetime.now(),
            asunto=caso["asunto"],
            reclamo=caso["codreclamo"],
            suministro=caso["suministro"],
            destinatario=caso["destinatario"],
            datos_reclamo=_construir(Reclamo, _loads(caso["datos_reclamo"])),
            medios_probatorios=_loads(caso["medios_probatorios"], []),
            objetivos=objetivos,
            bloques=bloques,
            documento_tecnico_operacional=_loads(caso["documento_tecnico"]),
            ventana_meses=[tuple(v) for v in _loads(caso["ventana_meses"], [])],
            fundamentacion_normativa=texto("fundamentacion"),
            estado_evaluacion=decision["estado_evaluacion"] if decision else "pendiente",
            motivos_evaluacion=[
                _construir(MotivoEvaluacion, m)
                for m in (_loads(decision["motivos"], []) if decision else [])
            ],
            mensaje_evaluacion=decision["mensaje"] if decision else None,
            origen_decision=decision["origen"] if decision else None,
            historial_decisiones=historial,
            veredicto=decision["veredicto"] if decision else None,
            conclusion=texto("conclusion"),
            dictamen=_loads(artefactos["dictamen"]["datos"]) if "dictamen" in artefactos else None,
            informe_texto_original=caso["informe_original"],
            propuesta_conciliacion=conciliacion,
            resolucion=texto("resolucion"),
            sesion_id=caso["sesion_id"],
            creado_por=caso["creado_por"],
            secuencia_hechos=_loads(caso["secuencia_hechos"], {}),
        )
        # Reconstruye las marcas de origen de los textos que no son generados,
        # para que una nueva sincronización no los reetiquete.
        for tipo, fila in artefactos.items():
            if fila["origen"] != ORIGEN_GENERADO:
                informe.marcas_origen[tipo] = (
                    fila["origen"], firma(fila["texto"], _loads(fila["datos"])),
                )
        return informe
