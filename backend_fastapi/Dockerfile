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

# Copy application code into a package directory so imports like
# `from backend_fastapi.*` resolve correctly when running from /app.
COPY . /app/backend_fastapi

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, requests; requests.get('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/docs', timeout=5)"

CMD ["sh", "-c", "uvicorn backend_fastapi.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
