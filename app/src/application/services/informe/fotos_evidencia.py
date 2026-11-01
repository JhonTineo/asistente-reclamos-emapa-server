"""Fotos que acompañan las evidencias del reclamo, tomadas de SYSCO.

SYSCO guarda, por cliente, los archivos que suben los celulares de campo y la
web (servicio ftp/generico/download/read, con el contenido en base64):

  LECT-<suc>-<suc>-<cliente>-<item>.jpg          foto del medidor de cada lectura
                                                 (observación "LECTURAS 2026 09")
  RECLA-REATENSION-IMG-...jpg                    fotos de la inspección del reclamo
  RECLA-REATENSION-FIRMA-...jpg                  firma del usuario (NO se usa)
  RECLA-INGRE-IMG-...pdf                         formulario de ingreso del reclamo

Este servicio pide solo los rangos de fechas necesarios (el día de la lectura
del mes reclamado y desde la recepción del reclamo hasta hoy), clasifica,
descarta firmas y copias repetidas (SYSCO repite las fotos de una inspección),
reduce las imágenes a un tamaño apto para la pantalla y el Word y guarda el
resultado en memoria unos minutos para no repetir la consulta (≈20 s).
"""

import base64
import hashlib
import io
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.application.services.informe.evidencias import construir_serie, periodos_reclamados, MES_ABREV
from app.src.core.model.informe_atencion import InformeAtencion

logger = logging.getLogger("services.fotos_evidencia")

LADO_MAXIMO = 1600          # px del lado mayor tras reducir
CALIDAD_JPEG = 80
MAX_INSPECCION = 8
MAX_LECTURA_POR_MES = 2
TTL_SEGUNDOS = 30 * 60

_RE_LECTURA = re.compile(r"LECTURAS?\s+(\d{4})\s+(\d{1,2})", re.I)


def _fecha(texto) -> date | None:
    if not texto:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(texto))
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(texto))
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _fin_de_mes(anio: int, mes: int) -> date:
    siguiente = date(anio + (mes == 12), mes % 12 + 1, 1)
    return siguiente - timedelta(days=1)


def _unir_rangos(rangos: list[tuple[date, date]]) -> list[tuple[date, date]]:
    unidos: list[list[date]] = []
    for ini, fin in sorted(rangos):
        if unidos and ini <= unidos[-1][1] + timedelta(days=1):
            unidos[-1][1] = max(unidos[-1][1], fin)
        else:
            unidos.append([ini, fin])
    return [(a, b) for a, b in unidos]


def clasificar(item: dict) -> str:
    """'lectura' | 'inspeccion' | 'formulario' | 'firma' | 'otra'."""
    nombre = str(item.get("pathimage") or item.get("nameimg") or "").upper()
    tipo = str(item.get("tiporecepcionimages") or "").upper()
    if "FIRMA" in nombre or "FIRMA" in tipo:
        return "firma"
    if nombre.startswith("LECT-") or _RE_LECTURA.search(str(item.get("observacion") or "")):
        return "lectura"
    if "RECLA-INGRE" in nombre or "RECLA-INGRE" in tipo:
        return "formulario"
    if "RECLA-" in nombre or "RECLA-" in tipo or "INSPEC" in nombre or "INSPEC" in tipo:
        return "inspeccion"
    return "otra"


def periodo_de_lectura(item: dict) -> tuple[int, int] | None:
    m = _RE_LECTURA.search(str(item.get("observacion") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def _decodificar(texto: str) -> bytes | None:
    if not texto or len(texto) < 100:
        return None
    texto = re.sub(r"^data:[^;]+;base64,", "", texto.strip())
    try:
        return base64.b64decode(texto + "=" * (-len(texto) % 4))
    except Exception:  # noqa: BLE001
        return None


def preparar_imagen(binario: bytes) -> tuple[bytes, str, int | None, int | None]:
    """Reduce una imagen (JPEG/PNG) a LADO_MAXIMO y la recomprime en JPEG.
    Devuelve (bytes, mime, ancho, alto). Si Pillow no está o falla, la deja tal cual."""
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(binario)) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
            salida = io.BytesIO()
            img.save(salida, format="JPEG", quality=CALIDAD_JPEG, optimize=True)
            return salida.getvalue(), "image/jpeg", img.width, img.height
    except Exception as exc:  # noqa: BLE001
        logger.warning("[FOTOS] No se pudo reducir la imagen (%s); se usa la original", exc)
        mime = "image/png" if binario[:4] == b"\x89PNG" else "image/jpeg"
        return binario, mime, None, None


def _mime(binario: bytes) -> str | None:
    if binario[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if binario[:4] == b"\x89PNG":
        return "image/png"
    if binario[:4] == b"%PDF":
        return "application/pdf"
    return None


class FotosEvidenciaService:
    _cache: dict[str, tuple[float, dict]] = {}
    _lock = threading.Lock()

    def __init__(self, emapa_api: PuertoEmapaAPI):
        self.emapa_api = emapa_api

    @classmethod
    def limpiar_cache(cls, codreclamo: str | None = None) -> None:
        with cls._lock:
            if codreclamo is None:
                cls._cache.clear()
            else:
                cls._cache.pop(codreclamo, None)

    def rangos(self, informe: InformeAtencion, hoy: date | None = None) -> list[tuple[date, date]]:
        """Rangos de fechas a consultar: alrededor de la lectura de cada mes
        reclamado, y desde la recepción del reclamo hasta hoy."""
        hoy = hoy or date.today()
        r = informe.datos_reclamo
        reclamados = periodos_reclamados(r.meses_reclamados if r else None)
        fechas_lectura = {(s["anio"], s["mes"]): _fecha(s.get("fecha_lectura")) for s in construir_serie(informe)}
        rangos = []
        for anio, mes in reclamados:
            f = fechas_lectura.get((anio, mes))
            if f:
                rangos.append((f - timedelta(days=1), min(f + timedelta(days=2), hoy)))
            else:
                rangos.append((date(anio, mes, 1), min(_fin_de_mes(anio, mes), hoy)))
        recepcion = _fecha(r.fecha_recepcion) if r else None
        if recepcion:
            rangos.append((recepcion, hoy))
        return _unir_rangos([(a, b) for a, b in rangos if a <= b])

    def obtener(self, informe: InformeAtencion, codsuc: str, codcliente: str,
                refrescar: bool = False) -> dict:
        clave = informe.reclamo
        with self._lock:
            en_cache = self._cache.get(clave)
        if en_cache and not refrescar and time.time() - en_cache[0] < TTL_SEGUNDOS:
            return {**en_cache[1], "desde_cache": True}

        t0 = time.perf_counter()
        r = informe.datos_reclamo
        reclamados = set(periodos_reclamados(r.meses_reclamados if r else None))
        recepcion = _fecha(r.fecha_recepcion) if r else None
        rangos = self.rangos(informe)

        crudos: list[dict] = []
        consultas = []
        for ini, fin in rangos:
            js = self.emapa_api.obtener_imagenes_cliente(codsuc, codcliente, ini.isoformat(), fin.isoformat())
            filas = js.get("data") if isinstance(js, dict) else None
            filas = filas if isinstance(filas, list) else []
            consultas.append({"desde": ini.isoformat(), "hasta": fin.isoformat(), "archivos": len(filas)})
            crudos.extend(f for f in filas if isinstance(f, dict))

        vistos: set[str] = set()
        fotos: list[dict] = []
        omitidas = {"firma": 0, "repetida": 0, "fuera_de_periodo": 0, "sin_contenido": 0}
        conteo = {"lectura": {}, "inspeccion": 0}
        # Más reciente primero, como lo devuelve SYSCO; se ordena al final.
        for item in crudos:
            categoria = clasificar(item)
            if categoria == "firma":
                omitidas["firma"] += 1
                continue
            fechareg = str(item.get("fechareg") or "")
            freg = _fecha(fechareg)
            periodo = periodo_de_lectura(item) if categoria == "lectura" else None
            if categoria == "lectura" and periodo not in reclamados:
                omitidas["fuera_de_periodo"] += 1
                continue
            if categoria in ("inspeccion", "formulario", "otra") and recepcion and freg and freg < recepcion:
                omitidas["fuera_de_periodo"] += 1
                continue
            if categoria == "lectura" and conteo["lectura"].get(periodo, 0) >= MAX_LECTURA_POR_MES:
                continue
            if categoria == "inspeccion" and conteo["inspeccion"] >= MAX_INSPECCION:
                continue
            binario = _decodificar(item.get("img64") or "")
            mime = _mime(binario) if binario else None
            if not binario or not mime:
                omitidas["sin_contenido"] += 1
                continue
            huella = hashlib.sha1(binario).hexdigest()
            if huella in vistos:
                omitidas["repetida"] += 1
                continue
            vistos.add(huella)

            ancho = alto = None
            if mime != "application/pdf":
                binario, mime, ancho, alto = preparar_imagen(binario)
            if categoria == "lectura":
                conteo["lectura"][periodo] = conteo["lectura"].get(periodo, 0) + 1
            elif categoria == "inspeccion":
                conteo["inspeccion"] += 1

            fotos.append({
                "id": huella[:12],
                "categoria": categoria,
                "titulo": self._titulo(categoria, periodo, item),
                "fecha": fechareg[:16] or None,
                "periodo": f"{MES_ABREV[periodo[1] - 1]} {periodo[0]}" if periodo else None,
                "nombre": item.get("pathimage") or item.get("nameimg"),
                "mime": mime,
                "ancho": ancho,
                "alto": alto,
                "kb": round(len(binario) / 1024),
                "base64": base64.b64encode(binario).decode("ascii"),
            })

        orden = {"lectura": 0, "inspeccion": 1, "formulario": 2, "otra": 3}
        fotos.sort(key=lambda f: (orden[f["categoria"]], f["fecha"] or ""))
        n = 0
        for f in fotos:
            if f["categoria"] == "inspeccion":
                n += 1
                f["titulo"] = f"Foto {n} de la inspección"

        resultado = {
            "codreclamo": informe.reclamo,
            "fotos": fotos,
            "consultas": consultas,
            "omitidas": omitidas,
            "resumen": {
                "lectura": sum(1 for f in fotos if f["categoria"] == "lectura"),
                "inspeccion": sum(1 for f in fotos if f["categoria"] == "inspeccion"),
                "formulario": sum(1 for f in fotos if f["categoria"] == "formulario"),
                "otra": sum(1 for f in fotos if f["categoria"] == "otra"),
            },
            "tiempo_s": round(time.perf_counter() - t0, 1),
            "obtenido": datetime.now().isoformat(timespec="seconds"),
            "desde_cache": False,
        }
        with self._lock:
            self._cache[clave] = (time.time(), resultado)
        logger.info("[FOTOS] reclamo=%s | consultas=%s | fotos=%s | omitidas=%s | %.1fs",
                    informe.reclamo, consultas, resultado["resumen"], omitidas, resultado["tiempo_s"])
        return resultado

    @staticmethod
    def _titulo(categoria: str, periodo, item: dict) -> str:
        if categoria == "lectura" and periodo:
            return f"Foto del medidor · lectura de {MES_ABREV[periodo[1] - 1]} {periodo[0]}"
        if categoria == "formulario":
            return "Formulario del reclamo"
        if categoria == "inspeccion":
            return "Foto de la inspección"
        return str(item.get("tiporecepcionimages") or "Archivo del cliente")
