FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_DISABLE_SYMLINKS_WARNING=1
ENV EASYOCR_HOME=/app/.easyocr

WORKDIR /app

# Install system dependencies required for OCR and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 libxext6 libxrender-dev libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Pre-download EasyOCR models by creating a temporary script
RUN mkdir -p /app/.easyocr && \
    python3 << 'EOF'
import os
import ssl
import logging

# Disable SSL verification for downloading models
ssl._create_default_https_context = ssl._create_unverified_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    logger.info("Starting EasyOCR model download...")
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False, model_storage_directory='/app/.easyocr', verbose=True)
    logger.info("✓ EasyOCR models successfully cached")
except Exception as e:
    logger.error(f"Failed to cache models: {e}", exc_info=True)
    raise
EOF

# Copy application code into a package directory so imports like
# `from backend_fastapi.*` resolve correctly when running from /app.
COPY . /app/backend_fastapi

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/tasks/', timeout=5)"

CMD ["uvicorn", "backend_fastapi.main:app", "--host", "0.0.0.0", "--port", "8000"]
