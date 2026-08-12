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
# Pinned to specific version + digest for supply-chain security
# To update: docker pull ghcr.io/astral-sh/uv:latest && docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:latest
# =============================================================================
FROM ghcr.io/astral-sh/uv:0.9.28@sha256:59240a65d6b57e6c507429b45f01b8f2c7c0bbeee0fb697c41a39c6a8e3a4cfb AS uv

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
# requirements-pg.txt pulls in requirements.txt + PostgreSQL deps (SQLAlchemy, psycopg2)
COPY requirements.txt requirements-pg.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --target /app/packages -r requirements-pg.txt

# =============================================================================
# Stage 3: Download DAWG vocabulary files from CDN
# =============================================================================
FROM python:3.11-slim AS dawg-downloader

# Default CDN URL for DAWG files (Digital Ocean Spaces)
ARG DAWG_BASE_URL=https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dawg

# The authoritative list of DAWG vocabulary files is _ALL_DAWGS in
# src/wordbase.py. Derive the download list from it at build time so the
# Dockerfile can never drift out of sync with the application code:
# adding or removing a DAWG in wordbase.py is automatically reflected here.
#
# list_dawgs.py parses wordbase.py with `ast` rather than importing it,
# because this stage has none of the app's dependencies installed and
# importing `config` would reach out to Google Secret Manager. See the
# module docstring for the full rationale.
#
# NOTE: this deliberately does NOT use a `RUN python - <<'EOF'` heredoc.
# Digital Ocean App Platform builds with kaniko, which does not support
# heredocs in RUN and silently discards the body, yielding an empty list
# and an image with no vocabularies. Keep the script in a file.
COPY src/wordbase.py /tmp/wordbase.py
COPY utils/list_dawgs.py /tmp/list_dawgs.py
RUN python /tmp/list_dawgs.py /tmp/wordbase.py > /tmp/dawgs.txt
RUN echo "DAWG files to download:" && cat /tmp/dawgs.txt && \
    while read -r dawg; do \
        echo "Downloading $dawg..." && \
        curl -fsSL "${DAWG_BASE_URL}/${dawg}" -o "${dawg}" || exit 1; \
    done < /tmp/dawgs.txt

# =============================================================================
# Stage 4: Build frontend assets (CSS and JS)
# TEMPORARY: This stage can be removed once the web UI is fully migrated
# to the separate React client (netskrafl-react).
# =============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Install build tools globally (smaller than full npm install).
# Majors are pinned to match package.json: TypeScript 6+ removed the
# module=AMD/outFile options that this project's tsconfig relies on.
RUN npm install -g less@4 typescript@5 uglify-js@3

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

# Install runtime dependencies (curl for health checks and cron jobs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Optional: Install supercronic for container-friendly cron scheduling
# Only installed if CRON_SECRET is set at build time (same var used at runtime)
# TARGETARCH is set by BuildKit; default to amd64 for platforms that don't set it
# SHA1 checksums from https://github.com/aptible/supercronic/releases/tag/v0.2.42
ARG CRON_SECRET
ARG TARGETARCH=amd64
RUN set -e; \
    if [ -n "${CRON_SECRET}" ]; then \
      SUPERCRONIC_VERSION=v0.2.42; \
      case "${TARGETARCH}" in \
        amd64) SUPERCRONIC_SHA1=b444932b81583b7860849f59fdb921217572ece2 ;; \
        arm64) SUPERCRONIC_SHA1=5193ea5292dda3ad949d0623e178e420c26bfad2 ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
      esac; \
      curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
        -o /usr/local/bin/supercronic \
      && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
      && chmod +x /usr/local/bin/supercronic; \
    else \
      echo "Skipping supercronic installation (CRON_SECRET not set)"; \
    fi

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

# Copy crontab and entrypoint script
COPY --link --chown=appuser:appuser crontab ./crontab
COPY --link --chown=appuser:appuser docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# Copy Alembic schema migrations (used by the entrypoint when
# DATABASE_BACKEND=postgresql)
COPY --link --chown=appuser:appuser alembic.ini ./alembic.ini
COPY --link --chown=appuser:appuser migrations/ ./migrations/

# Switch to non-root user
USER appuser

# Environment variables (defaults, override at runtime)
ENV PORT=8080 \
    TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/home/appuser/.local/lib/python3.11/site-packages \
    PATH=/home/appuser/.local/lib/python3.11/site-packages/bin:$PATH \
    GRPC_DNS_RESOLVER=native

# Health check using the /health/live endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health/live || exit 1

# Expose port
EXPOSE ${PORT}

# Start application via entrypoint script
# The script starts supercronic (if CRON_SECRET is set) and gunicorn
CMD ["./docker-entrypoint.sh"]
