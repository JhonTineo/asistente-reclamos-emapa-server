# -*- coding: utf-8 -*-
"""
Prueba de las APIs de IMÁGENES de SYSCO (solo lectura)
=======================================================
Objetivo: confirmar si SYSCO guarda fotos que sirvan como evidencia en el
informe de un reclamo (foto del medidor con la lectura del mes, fotos de la
inspección) y en qué formato las devuelve.

Servicios que prueba (encontrados en el Swagger de SYSCO):
  1. api-externa       GET  /ftp/tiporecepcion_img_x_subsistema           -> tipos de imagen
  2. api-micromedicion POST /water-meter-entry/ver-historial-lectmovil    -> lecturas del celular (foto1..3, GPS)
  3. api-micromedicion GET  /customer-reading/get-customer-images/info/{codsuc}/{codcliente}/{fileType}/{anio}/{mes}
  4. api-externa       POST /ftp/generico/download/read                   -> imágenes del cliente en un rango de fechas
  5. api-externa       POST /ftp/generico/download-base64                 -> contenido de una imagen

USO (con la VPN de EMAPA conectada):
  1. No hace falta token: el script pide tu usuario y contraseña de SYSCO
     (o usa SYSCO_TOKEN si lo defines y sigue vigente).
  2. Deja CODCLIENTE = 0 para que busque solo un reclamo con inspección.
  3. python herramientas/probar_fotos_sysco.py --login
     Opcional: --reclamo 12345  -> usa ese número de reclamo (uno que sepas que tiene inspección)

Resultado: carpeta volumes/prueba_fotos_<fecha>/ (volumes/ está en .gitignore),
con los JSON de cada respuesta, las fotos descargadas y resumen.txt.
Las fotos pueden mostrar el predio del usuario: no las compartas fuera de EMAPA.
"""
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3

# =============================== CONFIGURA AQUÍ ===============================
TOKEN = os.getenv("SYSCO_TOKEN", "") or "PEGA_AQUI_TU_TOKEN"

CODEMP = "001"
CODSEDE = "001"
# Si dejas CODCLIENTE = 0, el script BUSCA SOLO un reclamo reciente que tenga
# inspección y toma de ahí la sucursal, el cliente y el mes reclamado.
CODSUC = "001"          # sucursal del cliente (Tarapoto = 001)
CODCLIENTE = 0          # 0 = buscar automáticamente
ANIO = 2025             # año del mes reclamado (se ignora si la búsqueda es automática)
MES = 6                 # mes reclamado (se ignora si la búsqueda es automática)
MAX_RECLAMOS_A_REVISAR = 200
MAX_FOTOS_A_DESCARGAR = 8
# ==============================================================================

BASE = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
VERIFICAR_SSL = True
TIMEOUT = 120

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "volumes" / f"prueba_fotos_{datetime.now():%Y%m%d_%H%M}"
FOTOS = SALIDA / "fotos"
resumen: list[str] = []
rutas_imagen: list[tuple[str, str]] = []   # (origen, ruta/nombre de archivo)


def log(texto: str) -> None:
    print(texto)
    resumen.append(texto)


def guardar_json(nombre: str, datos) -> None:
    (SALIDA / f"{nombre}.json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def _respuesta(r):
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_texto_no_json": r.text[:500], "_content_type": r.headers.get("content-type")}


PREFIJO_OK: dict[str, str] = {}   # módulo de la API -> prefijo de token que funcionó


def _vacia(st, js) -> bool:
    """True si SYSCO no devolvió nada útil (401/403, o un 200 con cuerpo vacío)."""
    if st in (401, 403):
        return True
    if isinstance(js, dict) and "_texto_no_json" in js and not js["_texto_no_json"].strip():
        return True
    return False


def llamar(metodo: str, ruta: str, cuerpo=None):
    """Llama a SYSCO. Algunos servicios aceptan el token crudo (como el frontend)
    y otros 'Bearer <token>' (como el backend): si una forma no trae nada, se
    prueba la otra y se recuerda cuál funcionó para ese módulo."""
    url = BASE + ruta
    modulo = "/".join(ruta.split("/")[:3])
    orden = ("", "Bearer ")
    if PREFIJO_OK.get(modulo) == "Bearer ":
        orden = ("Bearer ", "")
    primera = None
    for prefijo in orden:
        try:
            r = requests.request(metodo, url, json=cuerpo, timeout=TIMEOUT, verify=VERIFICAR_SSL,
                                 headers={"Authorization": prefijo + TOKEN, "Accept": "application/json"})
        except requests.RequestException as e:
            return None, f"ERROR DE RED: {type(e).__name__}: {e}"
        st, js = _respuesta(r)
        if not _vacia(st, js) and st < 400:
            PREFIJO_OK[modulo] = prefijo
            return st, js
        primera = primera or (st, js)
    return primera


def detalle_error(js) -> str:
    """Mensaje corto de error que devuelve SYSCO (para el resumen)."""
    if isinstance(js, dict):
        for k in ("mensaje", "message", "error", "_texto_no_json", "_error"):
            if js.get(k):
                return str(js[k])[:200]
        return json.dumps(js, ensure_ascii=False)[:200]
    return str(js)[:200]


def filas(js):
    if isinstance(js, dict):
        d = js.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return [d]
    return js if isinstance(js, list) else []


def quitar_base64(obj):
    """Copia del objeto sin los textos base64 largos (para guardar JSON legibles)."""
    if isinstance(obj, dict):
        return {k: (f"<base64 {len(v)} caracteres>" if isinstance(v, str) and len(v) > 2000 else quitar_base64(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [quitar_base64(x) for x in obj]
    return obj


HASHES_GUARDADOS: set[str] = set()


def nombre_seguro(texto: str) -> str:
    """Nombre de archivo válido en Windows (sin ? * : etc.)."""
    texto = re.sub(r"\.(jpe?g|png|pdf)$", "", str(texto), flags=re.I)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", texto).strip("._")[:90] or "imagen"


def guardar_base64(texto: str, nombre: str) -> str | None:
    """Decodifica un base64 (con o sin prefijo data:) y lo guarda con la extensión
    correcta. Si la misma imagen ya se guardó (SYSCO a veces la repite), no la duplica."""
    import hashlib
    if not texto or len(texto) < 200:
        return None
    texto = re.sub(r"^data:[^;]+;base64,", "", texto.strip())
    try:
        binario = base64.b64decode(texto + "=" * (-len(texto) % 4))
    except Exception:
        return None
    huella = hashlib.sha1(binario).hexdigest()
    if huella in HASHES_GUARDADOS:
        return "repetida (misma imagen que otra ya guardada)"
    HASHES_GUARDADOS.add(huella)
    ext = ".jpg" if binario[:3] == b"\xff\xd8\xff" else ".png" if binario[:4] == b"\x89PNG" else \
          ".pdf" if binario[:4] == b"%PDF" else ".bin"
    destino = FOTOS / f"{nombre_seguro(nombre)}{ext}"
    destino.write_bytes(binario)
    return f"{destino.name} ({len(binario) / 1024:.0f} KB)"


def buscar_base64(obj) -> str | None:
    """Devuelve el texto más largo del objeto (suele ser el base64 de la imagen)."""
    candidatos = []
    def recorrer(o):
        if isinstance(o, dict):
            for v in o.values():
                recorrer(v)
        elif isinstance(o, list):
            for v in o:
                recorrer(v)
        elif isinstance(o, str) and len(o) > 200:
            candidatos.append(o)
    recorrer(obj)
    return max(candidatos, key=len) if candidatos else None


def _vencimiento(token: str) -> str:
    """Fecha de vencimiento del JWT (sin verificar firma), para diagnosticar."""
    try:
        parte = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))
        exp = payload.get("exp")
        return datetime.fromtimestamp(exp).strftime("%d/%m/%Y %H:%M") if exp else "sin fecha"
    except Exception:
        return "no es un JWT válido"


def iniciar_sesion() -> str:
    """Login de 2 pasos, igual que el frontend (src/app/state/auth.ts):
    vLogin con usuario/clave y luego seleccionar el sistema Comercial (002).
    La contraseña se pide por teclado, no se muestra ni se guarda."""
    import getpass
    print("\nInicio de sesión en SYSCO (la contraseña no se muestra ni se guarda)")
    usuario = input("  Usuario: ").strip()
    clave = getpass.getpass("  Contraseña: ")
    cuenta = base64.b64encode(f"{usuario}:{clave}:0".encode()).decode()
    r = requests.post(BASE + "/api-seguridad/usersystema/vLogin", json={"cuenta": cuenta},
                      timeout=TIMEOUT, verify=VERIFICAR_SSL)
    js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if js.get("response") != "EXITO" or not js.get("token"):
        sys.exit(f"Login rechazado: {js.get('mensaje') or r.status_code}")
    r = requests.get(BASE + "/api-seguridad/sistemas/seleccionar-sistema/002",
                     headers={"Authorization": js["token"]}, timeout=TIMEOUT, verify=VERIFICAR_SSL)
    js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if js.get("response") != "EXITO" or not js.get("token"):
        sys.exit(f"No se pudo seleccionar el sistema Comercial: {js.get('mensaje') or r.status_code}")
    log(f"Sesión iniciada como {usuario} (token válido hasta {_vencimiento(js['token'])})\n")
    return js["token"]


MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def _codigo_inspeccion(data: dict, campo: str):
    """nroinspeccion vinculado al reclamo (misma lógica que reclamo_service.py del backend)."""
    if data.get(f"cod{campo}"):
        return str(data[f"cod{campo}"])
    items = data.get(campo)
    if isinstance(items, list) and items and isinstance(items[-1], dict) and items[-1].get("nroinspeccion") is not None:
        return str(items[-1]["nroinspeccion"])
    return None


def _mes_reclamado(data: dict):
    """(año, mes) del mes reclamado ('JUNIO-2025') o, si no, de la fecha de recepción."""
    m = re.match(r"\s*([A-Za-zÁÉÍÓÚñÑ]+)[\s\-/]+(\d{4})", str(data.get("mesanio") or ""))
    if m and MESES.get(m.group(1).lower()):
        return int(m.group(2)), MESES[m.group(1).lower()]
    m = re.match(r"(\d{4})-(\d{2})", str(data.get("fecharec") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


# Claves cuyo valor se conserva en la estructura de ejemplo (no son datos personales).
CLAVES_VISIBLES = re.compile(r"^(cod|nro|num|mes|anio|fecha|estado|desc|des|tipo|procesado|flag|id)", re.I)
CLAVES_PERSONALES = re.compile(r"(nom|propiet|reclamante|direc|dni|docident|telef|celular|email|correo|motivo|observ|"
                               r"solicitante|creador|usuario|razonsocial|referencia)", re.I)


def estructura(obj, clave="", nivel=0):
    """Forma del JSON sin datos personales: deja los códigos/fechas/estados y
    reemplaza el resto por su tipo. Las listas muestran su largo y el 1er item."""
    if nivel > 6:
        return "…"
    if isinstance(obj, dict):
        return {k: estructura(v, k, nivel + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return {"_items": len(obj), "_primero": estructura(obj[0], clave, nivel + 1) if obj else None}
    if obj is None:
        return None
    if CLAVES_PERSONALES.search(clave) or not CLAVES_VISIBLES.search(clave):
        return f"<{type(obj).__name__}>"
    return obj if not isinstance(obj, str) else obj[:40]


def _listar(procesado: str, first: int, rows: int, nro: str = ""):
    cuerpo = {"codemp": CODEMP, "codsede": CODSEDE, "first": first, "rows": rows, "procesado": procesado,
              "campo": "nroreclamo" if nro else "ALL", "parametros": nro or "ALL", "tiporeclamo": "1"}
    st, js = llamar("POST", "/api-reclamos/reclamo/listar/parametros/atendidos", cuerpo)
    d = js.get("data") if isinstance(js, dict) else None
    lista = (d or {}).get("listar") or [] if isinstance(d, dict) else []
    total = (d or {}).get("totalrecords") if isinstance(d, dict) else None
    return st, js, lista, total


def _paginas(procesado: str):
    """Recorre el listado. SYSCO puede paginar por desplazamiento (first=0,20,40)
    o por número de página (first=0,1,2): si el 2do bloque sale vacío pero el
    total dice que hay más, se reintenta como número de página."""
    filas_pag = 20
    st, js, lista, total = _listar(procesado, 0, filas_pag)
    log(f"      listado procesado={procesado}: HTTP {st} · total según SYSCO: {total} · primera página: {len(lista)}")
    if st != 200:
        log(f"      respuesta: {detalle_error(js)}")
        guardar_json(f"0_listado_error_{procesado}", js)
        return
    yield from lista
    modo, k = "offset", 1
    while lista and (total is None or k * filas_pag < int(total)) and k * filas_pag < MAX_RECLAMOS_A_REVISAR:
        first = k * filas_pag if modo == "offset" else k
        st, js, lista, _ = _listar(procesado, first, filas_pag)
        if not lista and modo == "offset" and k == 1 and total and int(total) > filas_pag:
            modo = "pagina"
            st, js, lista, _ = _listar(procesado, 1, filas_pag)
            log(f"      (SYSCO pagina por número de página: first=1 trajo {len(lista)})")
        yield from lista
        k += 1


def _revisar(r, cont):
    """Pide el detalle de un reclamo del listado y devuelve (data, interna, externa, periodo)."""
    # Ojo: en el listado `codreclamo` es el TIPO de reclamo ("001"); el detalle
    # se pide con el número de reclamo (`nroreclamo`), igual que el frontend.
    ruta = (f"/api-reclamos/reclamo/obtener/detalle/{r.get('codsede') or CODSEDE}/{r.get('codsuc')}/"
            f"{r.get('nroreclamo') or r.get('codreclamo')}/{r.get('codcliente')}")
    st, det = llamar("GET", ruta)
    data = det.get("data") if isinstance(det, dict) else None
    data = data[0] if isinstance(data, list) and data else data
    if not isinstance(data, dict):
        cont["detalle_fallido"] += 1
        if cont["detalle_fallido"] >= 5 and not cont["detalle_ok"]:
            raise RuntimeError("detalle")
        if cont["detalle_fallido"] == 1:
            log(f"      Primer detalle fallido: HTTP {st} · {detalle_error(det)}")
            guardar_json("0_detalle_fallido_ejemplo", estructura(det))
        return None
    cont["detalle_ok"] += 1
    if cont["detalle_ok"] == 1:
        guardar_json("0_estructura_detalle_reclamo", estructura(det))
    for campo in ("inspeccion_interna", "inspeccion_externa"):
        v = data.get(campo)
        if isinstance(v, list) and v:
            cont[f"con_{campo}"] += 1
            if not cont.get(f"ej_{campo}"):
                cont[f"ej_{campo}"] = True
                guardar_json(f"0_estructura_{campo}", estructura(v))
    interna = _codigo_inspeccion(data, "inspeccion_interna")
    externa = _codigo_inspeccion(data, "inspeccion_externa")
    return data, interna, externa, _mes_reclamado(data)


def buscar_reclamo_con_inspeccion(nro: str = ""):
    """Recorre los reclamos más recientes (o el número indicado con --reclamo) y
    devuelve el primero con inspección vinculada."""
    from collections import Counter
    cont = Counter()
    if nro:
        log(f"[0] Buscando el reclamo número {nro}...")
        origen = (r for proc in ("0", "1") for r in _listar(proc, 0, 20, nro)[2])
    else:
        log("[0] Buscando automáticamente un reclamo reciente con inspección...")
        origen = (r for proc in ("0", "1") for r in _paginas(proc))
    revisados = 0
    for r in origen:
        if revisados >= MAX_RECLAMOS_A_REVISAR:
            break
        revisados += 1
        try:
            res = _revisar(r, cont)
        except RuntimeError:
            log("      Los 5 primeros detalles salieron vacíos (con token crudo y con 'Bearer'): se detiene la búsqueda.")
            log(f"      Ejemplo de ítem del listado: {json.dumps(estructura(r), ensure_ascii=False)[:300]}")
            guardar_json("0_item_listado_ejemplo", estructura(r))
            break
        time.sleep(0.15)
        if not res:
            continue
        data, interna, externa, periodo = res
        if (interna or externa) and not periodo:
            cont["sin_mes_reclamado"] += 1
        if (interna or externa) and periodo:
            log(f"      Encontrado tras revisar {revisados} reclamos: reclamo N° {r.get('nroreclamo')} · "
                f"cliente {r.get('codcliente')} · sucursal {r.get('codsuc')} · mes reclamado "
                f"{periodo[1]:02d}/{periodo[0]} · inspección interna {interna} · externa {externa}")
            guardar_json("0_reclamo_elegido", {"nroreclamo": r.get("nroreclamo"), "codcliente": r.get("codcliente"),
                                               "codsuc": r.get("codsuc"), "anio": periodo[0], "mes": periodo[1],
                                               "inspeccion_interna": interna, "inspeccion_externa": externa})
            return str(r.get("codsuc")), int(r.get("codcliente")), periodo[0], periodo[1]
    log(f"      No se encontró un reclamo con inspección entre los {revisados} revisados.")
    log(f"      Detalles leídos: {cont['detalle_ok']} · fallidos: {cont['detalle_fallido']} · "
        f"con lista de inspección interna: {cont['con_inspeccion_interna']} · externa: {cont['con_inspeccion_externa']} · "
        f"con inspección pero sin mes reclamado: {cont['sin_mes_reclamado']}")
    return None


def main():
    global CODSUC, CODCLIENTE, ANIO, MES, TOKEN
    if not VERIFICAR_SSL:
        urllib3.disable_warnings()
    FOTOS.mkdir(parents=True, exist_ok=True)
    TOKEN = TOKEN.strip().strip('"').strip()
    if TOKEN.lower().startswith("bearer "):
        TOKEN = TOKEN[7:].strip()
    if TOKEN.startswith("PEGA_AQUI") or not TOKEN or "--login" in sys.argv:
        TOKEN = iniciar_sesion()
    else:
        st, js = llamar("POST", "/api-reclamos/reclamo/listar/parametros/atendidos",
                        {"codemp": CODEMP, "codsede": CODSEDE, "first": 0, "rows": 1, "procesado": "0",
                         "campo": "ALL", "parametros": "ALL", "tiporeclamo": "1"})
        if st != 200 or not isinstance(js, dict) or js.get("status") != "SUCCESS":
            log(f"El token no sirve para el sistema Comercial (HTTP {st} · {detalle_error(js)}).")
            log(f"      Vencimiento según el token: {_vencimiento(TOKEN)}. Se pedirá iniciar sesión.")
            TOKEN = iniciar_sesion()
    if not CODCLIENTE:
        nro = sys.argv[sys.argv.index("--reclamo") + 1] if "--reclamo" in sys.argv[:-1] else ""
        elegido = buscar_reclamo_con_inspeccion(nro)
        if not elegido:
            (SALIDA / "resumen.txt").write_text("\n".join(resumen), encoding="utf-8")
            sys.exit("Prueba con --reclamo <número> (uno que sepas que tiene inspección) o completa CODSUC, CODCLIENTE, ANIO y MES a mano.")
        CODSUC, CODCLIENTE, ANIO, MES = elegido
        log("")
    CODCICLO = CODSUC   # en EMAPA el ciclo es igual a la sucursal
    log(f"Prueba de imágenes SYSCO · cliente {CODCLIENTE} · sucursal {CODSUC} · {MES:02d}/{ANIO}")
    log(f"Carpeta de resultados: {SALIDA}\n")

    # 1. Catálogo de tipos de imagen
    st, js = llamar("GET", "/api-externa/ftp/tiporecepcion_img_x_subsistema")
    guardar_json("1_tipos_recepcion_imagen", quitar_base64(js))
    tipos = filas(js)
    log(f"[1] Tipos de imagen: HTTP {st} · {len(tipos)} tipos")
    for t in tipos[:30]:
        log(f"      {json.dumps(t, ensure_ascii=False)[:160]}")

    # 2. Historial de lecturas tomadas con el celular (foto1..foto3, GPS)
    cuerpo = {"codemp": CODEMP, "codciclo": CODCICLO, "codsuc": CODSUC, "codcliente": CODCLIENTE, "anio": str(ANIO)}
    st, js = llamar("POST", "/api-micromedicion/water-meter-entry/ver-historial-lectmovil", cuerpo)
    guardar_json("2_historial_lectura_movil", quitar_base64(js))
    hist = filas(js)
    con_foto = [h for h in hist if any(h.get(f) for f in ("foto1", "foto2", "foto3"))]
    con_gps = [h for h in hist if h.get("latitud") and h.get("longitud")]
    log(f"\n[2] Historial de lectura móvil {ANIO}: HTTP {st} · {len(hist)} meses · con foto: {len(con_foto)} · con GPS: {len(con_gps)}")
    for h in hist[:12]:
        fotos = [str(h.get(f))[:60] for f in ("foto1", "foto2", "foto3") if h.get(f)]
        log(f"      mes {h.get('mes')}: lectura {h.get('lecturaultima')} · consumo {h.get('consumo')} · "
            f"estado '{h.get('c_desestlect') or h.get('estadolectura')}' · fecha {h.get('fechamovil')} · fotos {fotos}")
        for i, f in enumerate(("foto1", "foto2", "foto3"), 1):
            valor = h.get(f)
            if valor:
                guardado = guardar_base64(str(valor), f"lectura_{h.get('anio')}{str(h.get('mes')).zfill(2)}_foto{i}")
                if guardado:
                    log(f"         -> la foto venía en base64 dentro del JSON: {guardado}")
                else:
                    rutas_imagen.append((f"lectura móvil {h.get('mes')}/{h.get('anio')} {f}", str(valor)))

    # 3. Imágenes de lectura por mes (probando valores de fileType)
    log(f"\n[3] Imágenes de lectura por mes ({MES:02d}/{ANIO}), probando fileType:")
    for file_type in ("jpg", "JPG", "image", "imagen", "foto", "1", "2", "L", "LECTURA", "ALL"):
        ruta = f"/api-micromedicion/customer-reading/get-customer-images/info/{CODSUC}/{CODCLIENTE}/{file_type}/{ANIO}/{MES}"
        st, js = llamar("GET", ruta)
        lista = filas(js)
        log(f"      fileType={file_type:8} HTTP {st} · {len(lista)} imágenes · {str(js.get('message') or js.get('mensaje') or '')[:80] if isinstance(js, dict) else ''}")
        if lista:
            guardar_json(f"3_imagenes_lectura_{file_type}", quitar_base64(js))
            propias = [i for i in lista if str(i.get("codcliente")) == str(CODCLIENTE)]
            log(f"      -> del cliente {CODCLIENTE}: {len(propias)} · de otros clientes de la sucursal: {len(lista) - len(propias)}")
            for img in propias:
                if img.get("pathimage"):
                    log(f"         {img['pathimage']} · {img.get('fechareg')} · {img.get('observacion')}")
                    rutas_imagen.append((f"foto de lectura {MES:02d}/{ANIO}", img["pathimage"]))
            break
        time.sleep(0.3)

    # 4. Imágenes del cliente desde el mes reclamado hasta hoy (lecturas, inspección, reclamo)
    ini_d = f"{ANIO}-{MES:02d}-01"
    fin_d = f"{datetime.now():%Y-%m-%d}"
    log(f"\n[4] Imágenes del cliente del {ini_d} al {fin_d} (ftp/generico/download/read):")
    t0 = time.time()
    st, js = llamar("POST", "/api-externa/ftp/generico/download/read",
                    {"codsuc": CODSUC, "codcliente": CODCLIENTE, "fecha_inicial": ini_d, "fecha_final": fin_d})
    lista = filas(js)
    log(f"      HTTP {st} · {len(lista)} archivos · respondió en {time.time() - t0:.0f} s")
    if lista:
        guardar_json("4_imagenes_cliente", quitar_base64(js))
        guardados = 0
        for img in lista:
            tipo = img.get("tiporecepcionimages") or ("LECTURA" if str(img.get("pathimage", "")).startswith("LECT-") else "SIN-TIPO")
            linea = f"         {str(img.get('fechareg'))[:16]} · {tipo:22} · {img.get('tipoarchivo')} · {img.get('pathimage')}"
            if "FIRMA" in tipo:
                log(linea + " · (firma: no se descarga)")
                continue
            if guardados >= MAX_FOTOS_A_DESCARGAR:
                log(linea)
                continue
            guardado = guardar_base64(img.get("img64") or "", img.get("pathimage") or tipo)
            if guardado and not guardado.startswith("repetida"):
                guardados += 1
            log(linea + (f" -> {guardado}" if guardado else ""))
            if not guardado and img.get("pathimage"):
                rutas_imagen.append((f"archivo {tipo}", img["pathimage"]))

    # 5. Descargar el contenido de algunas imágenes por su ruta
    log(f"\n[5] Descarga de imágenes por ruta (ftp/generico/download-base64), máximo {MAX_FOTOS_A_DESCARGAR}:")
    if not rutas_imagen:
        log("      No se encontraron rutas de imagen en los pasos anteriores.")
    for i, (origen, ruta) in enumerate(rutas_imagen[:MAX_FOTOS_A_DESCARGAR], 1):
        st, js = llamar("POST", "/api-externa/ftp/generico/download-base64", {"nombreArchivo": ruta})
        guardado = guardar_base64(buscar_base64(js) or "", f"descarga_{i}")
        log(f"      {i}. {origen} · ruta {ruta[:70]} -> HTTP {st} · "
            f"{'GUARDADA ' + guardado if guardado else 'sin imagen: ' + json.dumps(quitar_base64(js), ensure_ascii=False)[:120]}")
        time.sleep(0.3)

    n = len(list(FOTOS.iterdir()))
    log(f"\nCONCLUSIÓN: {n} archivo(s) de imagen guardados en {FOTOS}")
    (SALIDA / "resumen.txt").write_text("\n".join(resumen), encoding="utf-8")


if __name__ == "__main__":
    main()
