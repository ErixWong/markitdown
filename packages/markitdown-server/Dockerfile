FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/markitdown /app/packages/markitdown
COPY packages/markitdown-ocr /app/packages/markitdown-ocr
COPY packages/markitdown-server /app/packages/markitdown-server

RUN pip install --no-cache-dir \
    -e /app/packages/markitdown[all] \
    -e /app/packages/markitdown-ocr \
    -e /app/packages/markitdown-server[ocr]

RUN mkdir -p /app/storage

ENV MARKITDOWN_STORAGE_DIR=/app/storage
ENV MARKITDOWN_OCR_ENABLED=true

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health 2>/dev/null || exit 1

ENTRYPOINT ["markitdown-server"]
CMD ["--host", "0.0.0.0", "--port", "8000"]