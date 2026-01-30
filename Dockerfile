# Dockerfile for Netskrafl/Explo backend
#
# Build:
#   docker build -t netskrafl .
#
# Run:
#   docker run -p 8080:8080 \
#     -e PROJECT_ID=netskrafl \
#     -e REDIS_URL=redis://redis:6379 \
#     -e GOOGLE_CREDENTIALS_BASE64=$(base64 -w0 credentials.json) \
#     netskrafl
#
# Note: DAWG vocabulary files (resources/*.bin.dawg) must exist before building.
# Generate them with: python utils/dawgbuilder.py all
# Or mount them as a volume at runtime.

# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: Get uv binary from official image
# =============================================================================
FROM ghcr.io/astral-sh/uv:latest AS uv

# =============================================================================
# Stage 2: Builder - install dependencies with uv (10-100x faster than pip)
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy uv binary from official image
COPY --from=uv /uv /usr/local/bin/uv

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with uv (uses cache mount for speed)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --target /app/packages -r requirements.txt

# =============================================================================
# Stage 3: Runtime - minimal production image
# =============================================================================
FROM python:3.11-slim

# Create non-root user first (before any file operations)
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser

# Install runtime dependencies (curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages with correct ownership (--chown is faster than separate chown)
COPY --link --chown=appuser:appuser --from=builder /app/packages /home/appuser/.local/lib/python3.11/site-packages

# Copy application code with correct ownership
COPY --link --chown=appuser:appuser src/ ./src/
COPY --link --chown=appuser:appuser static/ ./static/
COPY --link --chown=appuser:appuser templates/ ./templates/
COPY --link --chown=appuser:appuser resources/*.bin.dawg ./resources/

# Switch to non-root user
USER appuser

# Environment variables (defaults, override at runtime)
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/home/appuser/.local/lib/python3.11/site-packages \
    PATH=/home/appuser/.local/lib/python3.11/site-packages/bin:$PATH

# Health check using the /health/live endpoint
# start_interval: check frequently during startup for faster ready signal
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --start-interval=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health/live || exit 1

# Expose port
EXPOSE ${PORT}

# Start application with gunicorn
# Settings match app-netskrafl.yaml: 3 workers, 6 threads each, gthread worker class
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "3", \
     "--threads", "6", \
     "--worker-class", "gthread", \
     "--keep-alive", "10", \
     "--timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--capture-output", \
     "main:app"]
