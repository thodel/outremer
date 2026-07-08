# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="OUTREMER — AI-assisted prosopography pipeline"
LABEL org.opencontainers.image.description="AI-assisted prosopography of the medieval Levant (Crusades era, 11th–14th centuries)"
LABEL org.opencontainers.image.source="https://github.com/thodel/outremer"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install build deps + runtime deps in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .

# Runtime defaults — override with --env or -e flags
ENV GPUSTACK_BASE_URL="https://gpustack.unibe.ch/v1"
ENV OCR_ENGINE="easyocr"
ENV GPUSTACK_TIMEOUT="120"
ENV PYTHONUNBUFFERED="1"

ENTRYPOINT ["python", "scripts/run_pipeline.py"]
