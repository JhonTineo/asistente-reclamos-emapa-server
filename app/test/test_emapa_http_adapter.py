import pytest
from unittest.mock import patch, MagicMock
from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter

@pytest.fixture
def mock_http_get():
    """Mockea la función http_get_json para no hacer peticiones reales a EMAPA"""
    with patch('app.src.infrastructure.adapters.emapa_http_adapter.http_get_json') as mock:
        yield mock

def test_buscar_reclamo_emapa_exito(mock_http_get):
    # Arrange (Preparar)
    adapter = EmapaHttpAdapter()
    
    # Simulamos la respuesta que nos daría el ERP de EMAPA
    mock_response = {
        "data": {
            "nro_reclamo": "REC-123",
            "estado": "En proceso"
        }
    }
    mock_http_get.return_value = mock_response
    
    # Act (Actuar)
    resultado = adapter.buscar_reclamo(
        codsede="01", 
        codsuc="01", 
        codreclamo="123", 
        codcliente="CLI-999"
    )
    
    # Assert (Afirmar)
    assert resultado == mock_response
    assert resultado["data"]["nro_reclamo"] == "REC-123"
    
    # Verificamos que se haya llamado a la URL correcta internamente
    args, kwargs = mock_http_get.call_args
    assert "/api-reclamos/reclamo/obtener/detalle/01/01/123/CLI-999" in kwargs["url"]

def test_obtener_saldo_actual_exito(mock_http_get):
    # Arrange
    adapter = EmapaHttpAdapter()
    mock_response = {
        "data": {
            "saldo": 150.50,
            "moneda": "PEN"
        }
    }
    mock_http_get.return_value = mock_response
    
    # Act
    resultado = adapter.obtener_saldo_actual(codsuc="01", codcliente="CLI-999")
    
    # Assert
    assert resultado["data"]["saldo"] == 150.50
    args, kwargs = mock_http_get.call_args
    assert "/api-caja/cobranza/obtener-saldo-detalle-x-cliente/01/CLI-999" in kwargs["url"]
