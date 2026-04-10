# MarkItDown OCR MCP Server Dockerfile
# Multi-stage build for optimized image size

# Build stage
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy packages from monorepo
COPY packages/markitdown ./markitdown
COPY packages/markitdown-ocr ./markitdown-ocr
COPY packages/markitdown-ocr-mcp ./markitdown-ocr-mcp

# Build wheels
RUN pip wheel --wheel-dir=/wheels \
    ./markitdown[all] \
    ./markitdown-ocr \
    ./markitdown-ocr-mcp

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages from wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Create storage directory
RUN mkdir -p /app/storage

# Set environment variables
ENV MARKITDOWN_STORAGE_DIR=/app/storage
ENV MARKITDOWN_OCR_ENABLED=false

# Expose port for HTTP mode
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import markitdown_ocr_mcp; print('OK')" || exit 1

# Entry point - STDIO mode by default
ENTRYPOINT ["markitdown-ocr-mcp"]

# Default command (can be overridden for HTTP mode)
CMD []