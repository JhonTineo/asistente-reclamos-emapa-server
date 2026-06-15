EMAPA_API_BASE_URL = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"

EMAPA_ACCESS_TOKEN = "tu_token_aqui"

EMAPA_ENDPOINTS = {
    "saldo_actual": {
        "path": "/api-caja/cobranza/obtener-saldo-detalle-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "tarjeta_lectura": {
        "path": "/api-micromedicion/customer-reading/get-customer-card/info/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "record_facturacion": {
        "path": "/api-consulta/facturacion/obtener-record-facturacion-x-cliente-anio/{codsuc}/{codcliente}/{anio}",
        "method": "GET",
    },
    "corte_reapertura": {
        "path": "/api-consulta/catastro/obtener-corte-reapertura-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "inspeccion_externa": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-externa/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "inspeccion_interna": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-interna/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "buscar_reclamo": {
        "path": "/api-reclamos/reclamo/obtener/detalle/{codsede}/{codsuc}/{codreclamo}/{codcliente}",
        "method": "GET",
    },
}
