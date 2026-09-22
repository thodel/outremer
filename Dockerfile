FROM python:3.12-slim

# Links the GHCR package to this repository.
LABEL org.opencontainers.image.source="https://github.com/thodel/outremer" \
      org.opencontainers.image.description="OUTREMER prosopography pipeline: recognition and person extraction via GPUStack"

WORKDIR /app

# The same pinned set as CI and the tei nightly; bump deps by regenerating
# requirements.lock.txt, not here.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY scripts/ ./scripts/
COPY data/ ./data/
COPY pyproject.toml .

# The image carries the tool, not the corpus: source PDFs are not baked in
# (see .dockerignore). Mount inputs and outputs, pass the backend via env:
#   docker run --rm --env-file .env.gpustack \
#     -v "$PWD/pdfs:/app/data/raw:ro" -v "$PWD/site:/app/site" \
#     ghcr.io/thodel/outremer:latest
ENTRYPOINT ["python3", "scripts/run_pipeline.py", "--input-dir", "data/raw/"]
