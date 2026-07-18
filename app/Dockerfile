FROM python:3.11-slim

WORKDIR /code

# Dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements (dentro de ./app para que el codigo quede como paquete "app")
COPY requirements.txt ./app/requirements.txt

# Instalar dependencias Python
RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir -r ./app/requirements.txt


# Copiar proyecto dentro de ./app, asi los imports "app.src...." resuelven
COPY . ./app

# Puerto FastAPI
EXPOSE 8000

CMD ["uvicorn", "app.src.main:app", "--host", "0.0.0.0", "--port", "8000"]