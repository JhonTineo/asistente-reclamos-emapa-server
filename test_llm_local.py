from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# 1. Configurar la conexión con el servidor local de LM Studio
llm = ChatOpenAI(
    base_url="http://localhost:1234/v1",
    api_key="lm-studio",  # Clave ficticia requerida por el conector
    model="llama-3.2-3b-instruct",  # ID exacto de tu lista de modelos
    temperature=0.7
)

# 2. Definir el mensaje que le vamos a enviar
mensajes = [
    HumanMessage(content="Hola, ¿puedes confirmar que estás escuchando correctamente desde LM Studio?")
]

print("Enviando petición al modelo local...")

try:
    # 3. Ejecutar la inferencia
    respuesta = llm.invoke(mensajes)
    
    # 4. Mostrar el resultado en la terminal
    print("\n--- Respuesta del Modelo ---")
    print(respuesta.content)
    print("----------------------------")

except Exception as e:
    print(f"\nError al conectar con el modelo: {e}")
    print("Por favor, verifica que LM Studio tenga el servidor encendido en el puerto 1234.")