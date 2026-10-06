# Servicio CVP Contable (Railway). Se construye desde la RAÍZ del repositorio:
#   docker build -f servicio/Dockerfile .
FROM python:3.12-slim

# pdftotext (poppler) lo usan los lectores de 100% Banco y Plaza.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY parser/ /app/parser/
COPY servicio/requirements.txt /app/servicio/requirements.txt
RUN pip install --no-cache-dir /app/parser -r /app/servicio/requirements.txt

COPY servicio/ /app/servicio/
# Las pruebas no van a la imagen (usan archivos de clientes que tampoco están en el repositorio).
RUN rm -rf /app/servicio/tests

RUN useradd --create-home cvp
USER cvp
CMD ["sh", "-c", "uvicorn servicio.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
