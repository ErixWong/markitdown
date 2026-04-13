# MarkItDown API Dockerfile
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY packages/markitdown /app/packages/markitdown
COPY packages/markitdown-api /app/packages/markitdown-api

# Install Python dependencies
RUN pip install --no-cache-dir \
    -e /app/packages/markitdown \
    -e /app/packages/markitdown-api

# Create storage directory
RUN mkdir -p /app/storage

# Set environment variables
ENV MARKITDOWN_STORAGE_DIR=/app/storage
ENV MARKITDOWN_API_HOST=0.0.0.0
ENV MARKITDOWN_API_PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run server
CMD ["markitdown-api"]