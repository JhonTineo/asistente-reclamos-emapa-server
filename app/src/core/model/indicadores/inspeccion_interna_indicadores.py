# Traducción de códigos de EMAPA a texto legible (conocimiento de dominio).
from app.src.core.model.indicadores.targeta_lecturas_indicadores import INDICADORES_TARJETA_LECTURA

INDICADORES_INSPECCION_INTERNA = {
    "atipico": {
        "0": "No hubo consumos atípicos en la inspección.",
        "1": "Se detecto consumo atípico en la inspección.",
    },
   "estadoabas": {
        "1": "Abastecimiento Normal",
        "2": "Sin Abastecimiento"
    },
    # La categoría tarifaria (catetar) usa el MISMO código en toda EMAPA
    # (001=DOMESTICO, 002=DOM ANEXOS, 015=COMERCIAL, 022=INDUSTRIAL, 024=ESTATAL,
    # 026/027=SOCIAL, 101=DOMESTICO BENEF), verificado contra la tabla de tarifas
    # real de EMAPA. Se reutiliza el mapa autoritativo de la tarjeta como fuente
    # única, en vez de duplicar (y desincronizar) el mapeo con códigos inventados.
    "catetar": INDICADORES_TARJETA_LECTURA["catetar"],
}
