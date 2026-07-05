import sys
sys.path.insert(0, 'D:\\JhonTineo\\Documents\\GitHub\\asistente-reclamos-emapa-server')
from app.src.application.usecase.agents.analizador import AnalizadorAgent

agent = AnalizadorAgent()

ejemplos = [
    ("La empresa no quiere hacer la ampliación de diámetro de mi conexión de agua aunque ya tengo estudio de factibilidad positivo.", "Ampliación de diámetro"),
    ("No quieren reubicar mi conexión de agua potable y ya tengo estudio de factibilidad favorable.", "Negativa a reubicación"),
    ("La caja de registro de mi alcantarillado está dañada y no quieren hacer el mantenimiento.", "Negativa a mantenimiento de alcantarillado"),
    ("Necesito ampliar el diámetro de mi conexión de alcantarillado y ya tengo estudio de factibilidad positivo.", "Ampliación de diámetro de alcantarillado"),
    ("Quiero reubicar mi conexión de alcantarillado y tengo estudio de factibilidad favorable.", "Negativa a reubicación de alcantarillado"),
]

for detalle, esperado in ejemplos:
    resultado = agent.run(detalle)
    ok = "OK" if resultado['categoria_probable'] == esperado else "FAIL"
    print(f"[{ok}] Esperado: {esperado}")
    print(f"       Predicho: {resultado['categoria_probable']} (score: {resultado['score']:.4f})")
    print(f"       Detalle: {detalle[:60]}...")
    print()
