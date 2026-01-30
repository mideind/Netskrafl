# Dockerization Plan for Netskrafl/Explo

## Executive Summary

This document outlines the migration path from Google App Engine (GAE) Standard environment to Docker containers for the Netskrafl/Explo backend. The primary goals are:

1. **Reduce vendor lock-in** - Enable deployment on platforms beyond GAE
2. **Maintain compatibility** - Continue using Google Cloud APIs (NDB, Secret Manager)
3. **Preserve functionality** - Keep Firebase real-time communication working
4. **Enable future migration** - Prepare for eventual PostgreSQL + Supabase transition

### Key Constraints

- Must continue using Google Cloud NDB for the foreseeable future (data migration out of scope)
- Firebase Realtime Database must remain operational for client push notifications and presence
- Redis caching is already externalized and platform-agnostic
- OAuth2 flows with Google, Apple, and Facebook must continue to work

### Implementation Status (January 2025)

| Phase | Status | Platform |
|-------|--------|----------|
| Phase 1: Docker + Local Dev | ✅ Complete | Local |
| Phase 2: Cloud Run | ⏸️ Not started | GCP |
| Phase 3: Production Hardening | 🔶 Partial | - |
| Phase 4: Multi-Platform | ✅ Complete | Digital Ocean |

---

## Current Architecture Analysis

### GAE Configuration (`app-netskrafl.yaml`)

The current deployment uses:

- **Runtime**: Python 3.11
- **Instance class**: B4_1G (4 vCPU, 1GB RAM)
- **Scaling**: Basic scaling with max 2 instances, 5-minute idle timeout
- **Entry point**: `gunicorn -b :$PORT -w 3 --threads 6 --worker-class=gthread --keep-alive 10 --timeout 30 --pythonpath './src' main:app`
- **VPC connector**: For private Redis access (`vpc0c` in `us-central1`)
- **Static file handlers**: Extensive static file configuration with caching headers

### GAE-Specific Features - Migration Status

| Feature | Location | Status | Solution |
|---------|----------|--------|----------|
| `GAE_VERSION` env var | `main.py` | ✅ Migrated | `APP_VERSION` with fallback |
| `GAE_INSTANCE` env var | `main.py` | ✅ Migrated | `HOSTNAME` env var |
| `/_ah/start` handler | `main.py` | ✅ Kept | Works as-is, also have `/health/live` |
| `/_ah/warmup` handler | `main.py` | ✅ Migrated | `/health/ready` checks vocabularies |
| `/_ah/stop` handler | `main.py` | ✅ Kept | Works as-is |
| VPC Access Connector | `app.yaml` | ✅ N/A | Use platform networking |
| Static file handlers | `app.yaml` | ✅ Migrated | Flask serves root-level files |
| Cron jobs | `cron.yaml` | ✅ Migrated | supercronic built into container |
| Google Cloud Logging | `main.py` | ✅ Migrated | Platform-aware (GAE→GCP, Docker→stderr) |

---

## Implemented Infrastructure

### Dockerfile (5-Stage Build)

The production Dockerfile uses a multi-stage build for efficiency:

```dockerfile
# Stage 1: uv binary from official image
FROM ghcr.io/astral-sh/uv:latest AS uv

# Stage 2: Python dependencies with uv (10-100x faster than pip)
FROM python:3.11-slim AS builder
# ... installs requirements.txt to /app/packages

# Stage 3: Download DAWG files from CDN
FROM python:3.11-slim AS dawg-downloader
ARG DAWG_BASE_URL=https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg
# ... downloads 20 vocabulary files

# Stage 4: Build frontend assets (TEMPORARY - until React migration complete)
FROM node:20-alpine AS frontend-builder
# ... compiles LESS→CSS, TypeScript→JS, minifies

# Stage 5: Runtime
FROM python:3.11-slim
# ... copies from all previous stages, runs gunicorn
```

**Key features:**
- Uses `uv` for fast Python package installation
- Downloads DAWG vocabulary files from Digital Ocean Spaces CDN
- Builds frontend assets (CSS/JS) - temporary until React client is standalone
- Non-root user (`appuser`) for security
- Health check built into image

### docker-compose.yml

Local development environment with Redis:

```yaml
services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      PROJECT_ID: ${PROJECT_ID:-netskrafl}
      REDIS_URL: redis://redis:6379
      RUNNING_LOCAL: "false"
      APP_VERSION: ${APP_VERSION:-docker-dev}
      GOOGLE_APPLICATION_CREDENTIALS: /app/credentials/service-account.json
    volumes:
      - ./credentials:/app/credentials:ro
    depends_on:
      redis:
        condition: service_healthy
    develop:
      watch:
        - action: sync
          path: ./src
          target: /app/src
        - action: sync
          path: ./templates
          target: /app/templates

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
```

**Features:**
- Health-based dependency on Redis
- Live file sync for development (`docker compose watch`)
- Nginx load balancer available via `--profile scaled`

### DAWG Vocabulary Files

Binary vocabulary files are stored on Digital Ocean Spaces CDN:

- **Location**: `https://netskrafl-cdn.ams3.digitaloceanspaces.com/dawg/`
- **Files**: 20 `.bin.dawg` files (~13MB total)
- **Upload**: `python utils/dawgbuilder.py --upload` or `--upload-only`

The Dockerfile downloads these during build, eliminating the need to commit binary files to git.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PROJECT_ID` | Yes | GCP project ID (`netskrafl` or `explo-dev`) |
| `GOOGLE_CREDENTIALS_BASE64` | Yes* | Base64-encoded service account JSON |
| `REDIS_URL` | Yes | Redis connection URL (supports `rediss://` for TLS) |
| `APP_VERSION` | No | Version string for cache busting |
| `RUNNING_LOCAL` | No | Set `true` for local dev mode |
| `CRON_SECRET` | No | Enables cron: installs supercronic at build, starts it at runtime |

*Or `GOOGLE_APPLICATION_CREDENTIALS` (file path) or `GOOGLE_CREDENTIALS_JSON` (raw JSON)

### Health Endpoints

| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `/health/live` | Liveness probe | Process running (always 200) |
| `/health/ready` | Readiness probe | Vocabularies loaded + Redis connected |

### Platform-Aware Logging

```python
# Automatically detects environment:
if running_local:
    # Local dev: config.py logging
elif on_gae:  # GAE_APPLICATION or GAE_SERVICE set
    # Google Cloud Logging
else:
    # Docker/DO: stderr with timestamp format
    # Format: "2024-01-30 15:30:00 INFO [module] message"
```

### Cron Job Authentication

The `is_cron_request()` function in `firebase.py` supports multiple authentication methods:

```python
def is_cron_request() -> bool:
    # GAE Task Queue
    if headers.get("X-AppEngine-QueueName"):
        return True
    # GAE Cron
    if headers.get("X-Appengine-Cron") == "true":
        return True
    # Cloud Scheduler
    if request.environ.get("HTTP_X_CLOUDSCHEDULER") == "true":
        return True
    # External scheduler with secret token
    if CRON_SECRET and headers.get("X-Cron-Secret") == CRON_SECRET:
        return True
    # Development mode
    if running_local:
        return True
    return False
```

---

## Digital Ocean Deployment

Successfully deployed on Digital Ocean App Platform with:

### Configuration

- **App Platform**: Dockerfile-based deployment
- **Database**: Valkey 8 (Redis-compatible) managed database
- **Region**: AMS3 (Amsterdam)
- **Networking**: Private VPC between app and Valkey

### Environment Variables on DO

```
PROJECT_ID=netskrafl
GOOGLE_CREDENTIALS_BASE64=<base64-encoded service account JSON>
REDIS_URL=rediss://default:<password>@private-xxx.valkey.db.ondigitalocean.com:25061
APP_VERSION=<commit-hash or version>
```

### Valkey Compatibility

Valkey is a Redis fork that's fully compatible with the `redis` Python library. No code changes required - just use the connection URL.

---

## Remaining Work

### Phase 2: Cloud Run (Not Started)

Cloud Run deployment would reuse existing GCP infrastructure:

- VPC connector for Memorystore Redis
- Cloud Scheduler for cron jobs
- Same service account credentials

### Phase 3: Production Hardening

| Item | Status | Notes |
|------|--------|-------|
| CDN for static assets | ❌ | Currently served by Flask |
| Load testing | ❌ | Not performed |
| Auto-scaling policies | 🔶 | Platform-dependent |
| Monitoring/alerting | 🔶 | Platform-dependent |

### Phase 4: Multi-Platform (Partial)

| Platform | Status | Notes |
|----------|--------|-------|
| Digital Ocean | ✅ Complete | App Platform + Valkey |
| Kubernetes | ❌ | Manifests not created |
| AWS | ❌ | Not started |

### Cron Job Setup

Cron jobs use **supercronic** (a container-friendly cron implementation), controlled by `CRON_SECRET`:

| Job | Endpoint | Schedule | Auth |
|-----|----------|----------|------|
| Online sync | `/connect/update` | Every 2 min | `X-Cron-Secret` header |
| Stats | `/stats/run` | Daily 03:00 UTC | `X-Cron-Secret` header |
| Ratings | `/stats/ratings` | Daily 03:45 UTC | `X-Cron-Secret` header |

**How `CRON_SECRET` works:**

| Phase | CRON_SECRET set | CRON_SECRET not set |
|-------|-----------------|---------------------|
| Build | Supercronic installed | Supercronic skipped |
| Runtime | Supercronic starts | Cron disabled |

**Configuration:**
- Set `CRON_SECRET` as an environment variable visible to both build and runtime
- On Digital Ocean: Add to App-level environment variables (applies to both)
- On Cloud Run: Don't set `CRON_SECRET` (use Cloud Scheduler instead)
- Jobs authenticate via `X-Cron-Secret` header to localhost endpoints
- All times are UTC (`TZ=UTC` and `CRON_TZ=UTC` set explicitly)
- Architecture-aware binary (supports amd64, arm64) with SHA1 verification

---

## Risk Summary

| Risk | Severity | Status | Notes |
|------|----------|--------|-------|
| Redis connectivity (non-GCP) | High | ✅ Resolved | Valkey on DO works |
| Cold start latency | Medium | ✅ Managed | Readiness probe waits for vocabularies |
| Firebase latency (non-GCP) | Low | ✅ Acceptable | Mostly async operations |
| Static file performance | Low | 🔶 | Flask serves; CDN recommended for scale |
| Cron job authentication | Low | ✅ Ready | Token-based auth implemented |

---

## Conclusion

The Netskrafl/Explo backend has been successfully dockerized and deployed on Digital Ocean. The implementation:

1. **Maintains full compatibility** with Google Cloud services (NDB, Secret Manager, Firebase)
2. **Works with Redis-compatible databases** (tested with DO Valkey)
3. **Supports multiple credential methods** for flexibility across platforms
4. **Provides platform-aware logging** (GCP on GAE, stderr elsewhere)
5. **Includes health endpoints** for container orchestration
6. **Built-in cron scheduling** via supercronic (no external scheduler needed)

The codebase now supports deployment on GAE (original), Digital Ocean (tested), and is ready for Cloud Run or Kubernetes with minimal additional work.

### Files Modified/Created

| File | Change |
|------|--------|
| `Dockerfile` | Created - 5-stage build with supercronic |
| `docker-compose.yml` | Created - local dev environment |
| `docker-entrypoint.sh` | Created - starts supercronic + gunicorn |
| `crontab` | Created - cron job definitions |
| `.dockerignore` | Created - excludes unnecessary files |
| `nginx.conf` | Created - load balancer config |
| `src/main.py` | Health endpoints, platform-aware logging, cache busting |
| `src/config.py` | Added `ON_GAE` and `ON_GCP` detection |
| `src/cache.py` | REDIS_URL support |
| `src/authmanager.py` | Credential handling from env vars |
| `src/firebase.py` | `is_cron_request()` with platform-aware auth |
| `src/wordbase.py` | `is_initialized()` for readiness probe |
| `utils/dawgbuilder.py` | `--upload` flag for DO Spaces |
