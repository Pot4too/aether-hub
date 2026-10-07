FROM python:3.12-slim-bookworm

WORKDIR /app

COPY ingest/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/aether_shared ./aether_shared
COPY ingest/app ./app

CMD ["python", "-m", "app.main"]
