import pytest
from qdrant_client import QdrantClient

# Importamos el Adaptador que acabamos de crear
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter

def test_qdrant_adapter_flujo_completo():
    """
    Prueba el flujo completo: Crear colección, insertar vectores y buscar.
    Al pasar location=":memory:", Qdrant corre en la memoria RAM y no necesita Docker!
    ¡Esta es la magia de la inyección de dependencias!
    """
    
    # 1. Arrange (Preparar)
    # Creamos un cliente en memoria para aislar la prueba de la base de datos real
    cliente_en_memoria = QdrantClient(location=":memory:")
    
    # Inyectamos el cliente de prueba a nuestro adaptador
    adapter = QdrantAdapter(client=cliente_en_memoria, collection_name="test_collection", dim=2)
    
    # Datos de prueba
    vector_data = [
        {"id": 1, "vector": [0.1, 0.9], "payload": {"texto": "agua"}},
        {"id": 2, "vector": [0.9, 0.1], "payload": {"texto": "tierra"}},
    ]
    query_vector = [0.1, 0.95] # Muy similar al id 1
    
    # 2. Act (Actuar)
    adapter.create_collection()
    adapter.upsert(points=vector_data)
    resultados = adapter.search(vector=query_vector, top_k=1)
    
    # 3. Assert (Verificar)
    assert len(resultados) == 1
    assert resultados[0]["id"] == 1
    assert resultados[0]["payload"]["texto"] == "agua"
    # El score de similitud (Cosine) debe ser alto porque los vectores son parecidos
    assert resultados[0]["score"] > 0.9
