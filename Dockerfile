# Studio — container for Render (or any Docker host)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    U2NET_HOME=/data/models \
    HOSTED=1

WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install -r requirements.txt -r requirements-server.txt \
 && python -m playwright install --with-deps chromium \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .
RUN rm -f .env && mkdir -p /data

# One worker process (the publish lock and job queue live in memory), many threads for concurrent users.
CMD gunicorn app:app --workers 1 --threads 16 --timeout 900 --bind 0.0.0.0:${PORT:-10000} --access-logfile -
