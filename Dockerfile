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

# =============================================================================
# Stage 1: Builder - install dependencies
# =============================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies to user site-packages
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
# Stage 2: Runtime - minimal production image
# =============================================================================
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY static/ ./static/
COPY templates/ ./templates/
COPY resources/*.bin.dawg ./resources/

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Environment variables (defaults, override at runtime)
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

# Health check using the new /health/live endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
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
