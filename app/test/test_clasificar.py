import sys
sys.path.insert(0, 'D:\\JhonTineo\\Documents\\GitHub\\asistente-reclamos-emapa-server')
from app.src.application.usecase.agents.analizador import AnalizadorAgent

agent = AnalizadorAgent()

ejemplos = [
    "No estoy conforme con el cobro de los recibos del 2025, ya que mis consumos son de 23 m3 aproximadamente.",
    "Ya pagué el recibo pero me lo vuelven a cobrar.",
    "Tengo una fuga en la conexión domiciliaria.",
    "El medidor registró un consumo mayor al que realmente hice.",
    "Me facturaron consumo promedio y el monto no me parece correcto.",
    "El alcantarillado está atorado en la conexión de mi casa.",
    "Se me facturó un servicio que no tengo conexión porque está cerrada.",
    "Me cobraron cargos de alcantarillado que no corresponden.",
    "MI FACTURA CON MI MEDIDOREL DIA DE HOY 26/12/2025 ME PERCATO QUE LA LECTURA ACTUAL DE MI MEDIDOR ES DE 733 Y NI SOBREPASA TODAVIA LOS 742 QUE INDICA MI RECIBO.",
    "Quiero que reubiquen mi conexión domiciliaria porque ya tengo estudio de factibilidad favorable.",
]

for detalle in ejemplos:
    resultado = agent.run(detalle)
    print(f"Detalle: {detalle[:55]}...")
    print(f"  -> {resultado['categoria_probable']} (score: {resultado['score']:.4f})")
    print()
