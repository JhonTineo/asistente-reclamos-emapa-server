import re
import unicodedata

# Nombres de tipo tal como están en el anexo / colección.
T_MEDIDO = "Consumo medido"
T_PROMEDIO = "Consumo Promedio"
T_ASIGNACION = "Asignación de Consumo"
T_CERRADO = "Consumo no realizado por servicio cerrado"
T_OTRO_SUM = "Consumo atribuible a otro suministro"
T_USR_ANT = "Consumo atribuible a usuario anterior del suministro"
T_PAGO = "Pago no procesado"
T_TARIFA = "Tipo de Tarifa"
T_CONCEPTOS = "Conceptos emitidos"

STRONG, WEAK = 3, 1

# Reglas: tipo -> {"strong": [...], "weak": [...]}. Los patrones se comparan
# sobre el texto normalizado (minúsculas, sin tildes).
REGLAS: dict[str, dict[str, list[str]]] = {
    T_OTRO_SUM: {
        "strong": ["cruce de medidor", "cruce de suministro", "cruce",
                   "otro suministro", "pertenece al suministro",
                   "no es mi medidor", "medidor no es el mio",
                   "consumo de mi vecino", "dos suministros"],
        "weak": ["vecino", "confusion de suministro"],
    },
    T_CONCEPTOS: {
        "strong": ["desague", "valores maximo", "vma", "duplicidad",
                   "cobro de desague", "concepto que no", "conceptos que no",
                   "cargos indebidos", "cargo indebido", "devolucion",
                   "compensacion", "pozo septico"],
        "weak": ["concepto", "alcantarillado", "duplicado"],
    },
    T_TARIFA: {
        "strong": ["categoria", "recategoriz", "cambio de categoria",
                   "comercial a domestico", "domestico a comercial",
                   "tarifa comercial", "cambio de comercial",
                   "unidades de uso", "cambio de unidades"],
        "weak": ["comercial", "domestico", "industrial"],
    },
    T_CERRADO: {
        "strong": ["servicio cerrado", "consumo cerrado", "cerrado desde",
                   "no cuenta con el servicio", "no cuenta con servicio",
                   "servicio cortado", "predio esta cerrado",
                   "sin servicio desde", "consumo no realizado",
                   "no tengo servicio", "no hago uso del servicio",
                   "no estoy haciendo uso del servicio"],
        "weak": ["no vive nadie", "nadie habita", "corte", "reconexion"],
    },
    T_ASIGNACION: {
        "strong": ["asignacion de consumo", "asignacion", "asignado",
                   "asignando", "cargos fijos", "sin medidor",
                   "no tengo el medidor instalado", "medidor robado",
                   "terreno libre", "no tiene conexion interna",
                   "medidor sustraido", "medidor no instalado"],
        "weak": ["proyectado", "no instalaron el medidor"],
    },
    T_PROMEDIO: {
        "strong": ["promediando", "promediada", "facturacion promediada",
                   "promedio de sus", "promedio de mis", "promedio que le"],
        "weak": ["promedio", "consumo estimado"],
    },
    T_PAGO: {
        "strong": ["ya pague", "pago no procesado", "doble cobro",
                   "pagado dos veces", "cobraron dos veces", "pago duplicado",
                   "voucher", "vuelven a cobrar", "cobrar dos veces",
                   "recibo duplicado", "ya cancele"],
        "weak": ["comprobante de pago"],
    },
    T_USR_ANT: {
        "strong": ["usuario anterior", "dueno anterior", "titular anterior",
                   "inquilino anterior", "antes de ser titular",
                   "recien compre el predio", "propietario anterior"],
        "weak": ["cambio de titular", "deuda anterior"],
    },
    T_MEDIDO: {
        "strong": ["medidor marca", "el medidor registra", "segun medidor",
                   "m3 registrados", "lectura del medidor", "refacturacion",
                   "fuga"],
        "weak": ["consumo muy elevado", "consumo elevado", "muy elevado"],
    },
}


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto


def clasificar_rapido(motivo: str, desc_tipo_reclamo: str | None = None) -> dict:
    """Clasifica un reclamo por reglas. Devuelve tipo, score, confianza y
    los tipos alternativos con su puntaje (para trazabilidad)."""
    texto = _normalizar(motivo or "")

    if not texto.strip():
        return {"tipo": None, "score": 0, "confianza": "nula",
                "metodo": "reglas", "candidatos": []}

    puntajes: dict[str, int] = {}
    for tipo, kws in REGLAS.items():
        s = sum(STRONG for k in kws["strong"] if k in texto)
        s += sum(WEAK for k in kws["weak"] if k in texto)
        if s > 0:
            puntajes[tipo] = s

    if not puntajes:
        # Reclamo de facturación sin señales distintivas -> por defecto, el
        # caso más común es Consumo medido (predio con medidor).
        es_facturacion = desc_tipo_reclamo is None or "factura" in _normalizar(desc_tipo_reclamo)
        tipo_def = T_MEDIDO if es_facturacion else None
        return {"tipo": tipo_def, "score": 0, "confianza": "baja",
                "metodo": "reglas", "candidatos": []}

    ordenados = sorted(puntajes.items(), key=lambda x: -x[1])
    mejor, mejor_score = ordenados[0]
    segundo_score = ordenados[1][1] if len(ordenados) > 1 else 0
    margen = mejor_score - segundo_score

    # Confianza según puntaje y margen sobre el segundo candidato.
    if mejor_score >= STRONG and margen >= STRONG:
        confianza = "alta"
    elif mejor_score >= STRONG:
        confianza = "media"
    else:
        confianza = "baja"

    return {
        "tipo": mejor,
        "score": mejor_score,
        "confianza": confianza,
        "metodo": "reglas",
        "candidatos": [{"tipo": t, "score": s} for t, s in ordenados[:3]],
    }
