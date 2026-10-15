FROM python:3.12-slim

# Links the GHCR package to this repository.
LABEL org.opencontainers.image.source="https://github.com/thodel/outremer" \
      org.opencontainers.image.description="OUTREMER prosopography pipeline: recognition and person extraction via GPUStack"

WORKDIR /app

# git: the ATR client is pinned as a git+https URL (ADR 0002) — pip ignores
# #subdirectory on archive URLs, so the slim image needs the binary to install
# the lock file at all. Removed again after the install; it is not a runtime need.
# The same pinned set as CI and the tei nightly; bump deps by regenerating
# requirements.lock.txt, not here.
COPY requirements.lock.txt .
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && pip install --no-cache-dir -r requirements.lock.txt \
    && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY scripts/ ./scripts/
# The evidence-first JSON Schema and SHACL shapes: every document is
# validated against them, so without this directory every run fails.
COPY schema/ ./schema/
COPY data/ ./data/
COPY pyproject.toml .

# The image carries the tool, not the corpus: source PDFs are not baked in
# (see .dockerignore). Mount inputs and outputs, pass the backend via env:
#   docker run --rm --env-file .env.gpustack \
#     -v "$PWD/pdfs:/app/data/raw:ro" -v "$PWD/site:/app/site" \
#     ghcr.io/thodel/outremer:latest
ENTRYPOINT ["python3", "scripts/run_pipeline.py", "--input-dir", "data/raw/"]
