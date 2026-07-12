FROM python:3.12-slim

WORKDIR /app

# Install system deps for easyocr (optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install easyocr if desired (CPU OCR fallback)
RUN pip install --no-cache-dir easyocr

COPY scripts/ ./scripts/
COPY data/ ./data/
COPY pyproject.toml .

# Default: run pipeline on data/raw/
ENTRYPOINT ["python3", "scripts/run_pipeline.py", "--input-dir", "data/raw/"]