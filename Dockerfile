FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JM_DATA_DIR=/app/data \
    JM_DOWNLOAD_DIR=/downloads \
    JM_HOST=0.0.0.0 \
    JM_PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /downloads

EXPOSE 8000

CMD ["sh", "-c", "uvicorn jm_downloader.main:app --host ${JM_HOST:-0.0.0.0} --port ${JM_PORT:-8000}"]
