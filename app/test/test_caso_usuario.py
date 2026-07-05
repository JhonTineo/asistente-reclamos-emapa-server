import sys
sys.path.insert(0, 'D:\\JhonTineo\\Documents\\GitHub\\asistente-reclamos-emapa-server')
from app.src.application.usecase.agents.analizador import AnalizadorAgent

agent = AnalizadorAgent()

detalle = "BUENAS TARDES, NO ESTOY CONFORME CON LO FACTURADO DEL MES DE NOVIEMBRE 2025. REVISANDO MI FACTURA CON MI MEDIDOREL DíA DE HOY 26/12/2025 ME PERCATO QUE LA LECTURA ACTUAL DE MI MEDIDOR ES DE 733 Y NI SOBREPASA TODAVíA LOS 742 QUE INDICA MI RECIBO QUE CONSUMí. PONGO EN CONOCIMIENTO PARA QUE SE APERSONEN A VERIFICAR MI RECLAMO. GRACIAS"

resultado = agent.run(detalle)
print(f"Tipo: {resultado['categoria_probable']}")
print(f"Score: {resultado['score']:.4f}")
print(f"Descripción: {resultado['descripcion']}")
