# Studio — container for Render (free or paid) or any Docker host
FROM python:3.12-slim-bookworm

ARG INSTALL_CUTOUTS=0
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DATA_DIR=/data \
    U2NET_HOME=/data/models \
    HOSTED=1

WORKDIR /app
COPY requirements.txt requirements-server.txt ./
# Playwright's helper needs libatomic1 before it can install the browser and its other system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && pip install -r requirements.txt -r requirements-server.txt \
 && python -m playwright install --with-deps chromium \
 && if [ "$INSTALL_CUTOUTS" = "1" ]; then pip install "rembg[cpu]"; fi \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY . .
RUN rm -f .env && mkdir -p /data

# One worker process (the publish lock and job queue live in memory), threads for concurrent users.
CMD gunicorn app:app --workers 1 --threads 8 --timeout 900 --bind 0.0.0.0:${PORT:-10000} --access-logfile -
