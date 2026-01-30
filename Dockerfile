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
# DAWG vocabulary files are downloaded from Digital Ocean Spaces during build.
# To use a different source, override DAWG_BASE_URL:
#   docker build --build-arg DAWG_BASE_URL=https://your-cdn.com/dawg -t netskrafl .
#
# To upload new DAWG files after building them locally:
#   python utils/dawgbuilder.py all --upload

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
# Stage 3: Download DAWG vocabulary files from CDN
# =============================================================================
FROM python:3.11-slim AS dawg-downloader

# Default CDN URL for DAWG files (Digital Ocean Spaces)
ARG DAWG_BASE_URL=https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dawg

# List of all DAWG files to download
# These are the vocabulary files for different languages and robot difficulty levels
RUN for dawg in \
    algeng.bin.dawg \
    amlodi.bin.dawg \
    midlungur.bin.dawg \
    nsf2023.aml.bin.dawg \
    nsf2023.bin.dawg \
    nsf2023.mid.bin.dawg \
    nynorsk2024.aml.bin.dawg \
    nynorsk2024.bin.dawg \
    nynorsk2024.mid.bin.dawg \
    ordalisti.bin.dawg \
    osps37.aml.bin.dawg \
    osps37.bin.dawg \
    osps37.mid.bin.dawg \
    otcwl2014.aml.bin.dawg \
    otcwl2014.bin.dawg \
    otcwl2014.mid.bin.dawg \
    sowpods.aml.bin.dawg \
    sowpods.bin.dawg \
    sowpods.mid.bin.dawg \
    twl06.bin.dawg; do \
        echo "Downloading $dawg..." && \
        curl -fsSL "${DAWG_BASE_URL}/${dawg}" -o "${dawg}" || exit 1; \
    done

# =============================================================================
# Stage 4: Build frontend assets (CSS and JS)
# TEMPORARY: This stage can be removed once the web UI is fully migrated
# to the separate React client (netskrafl-react).
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Install build tools globally (smaller than full npm install)
RUN npm install -g less typescript uglify-js

# Copy frontend source files
COPY static/ ./static/

# Build CSS from LESS
RUN lessc static/skrafl-explo.less static/skrafl-explo.css && \
    lessc static/skrafl-curry.less static/skrafl-curry.css

# Build JS: TypeScript → JS, concatenate legacy JS, minify
RUN cd static && tsc && \
    mkdir -p built && \
    cat js/*.js > built/netskrafl.js && \
    uglifyjs built/explo.js -o built/explo.min.js --source-map && \
    uglifyjs built/netskrafl.js -o built/netskrafl.min.js --source-map

# =============================================================================
# Stage 5: Runtime - minimal production image
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

# Copy built frontend assets (CSS and JS) from frontend-builder stage
# These overwrite the source files with compiled versions
COPY --link --chown=appuser:appuser --from=frontend-builder /app/static/*.css ./static/
COPY --link --chown=appuser:appuser --from=frontend-builder /app/static/built/ ./static/built/

# Copy DAWG files from downloader stage
COPY --link --chown=appuser:appuser --from=dawg-downloader /dawg/*.bin.dawg ./resources/

# Switch to non-root user
USER appuser

# Environment variables (defaults, override at runtime)
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/home/appuser/.local/lib/python3.11/site-packages \
    PATH=/home/appuser/.local/lib/python3.11/site-packages/bin:$PATH

# Health check using the /health/live endpoint
# Note: --start-interval removed for compatibility with older Docker versions (e.g., Digital Ocean)
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
