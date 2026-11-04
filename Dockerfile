# Public search app (read-only). OCR-based ingestion (Pensol, Meko catalogue) needs macOS Vision and runs from the laptop,
# straight into the hosted database; this image only serves the catalogue.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest ./ingest
COPY web ./web
COPY data/config ./data/config
ENV PYTHONUNBUFFERED=1 TRUST_PROXY=1
EXPOSE 8000
CMD ["uvicorn", "ingest.web:app", "--host", "0.0.0.0", "--port", "8000"]
