# Dockerization Plan for Netskrafl/Explo

## Executive Summary

This document outlines the migration path from Google App Engine (GAE) Standard environment to Docker containers for the Netskrafl/Explo backend. The primary goals are:

1. **Reduce vendor lock-in** - Enable deployment on platforms beyond GAE
2. **Maintain compatibility** - Continue using Google Cloud APIs (NDB, Secret Manager, Logging)
3. **Preserve functionality** - Keep Firebase real-time communication working
4. **Enable future migration** - Prepare for eventual PostgreSQL + Supabase transition

### Key Constraints

- Must continue using Google Cloud NDB for the foreseeable future (data migration out of scope)
- Firebase Realtime Database must remain operational for client push notifications and presence
- Redis caching is already externalized and platform-agnostic
- OAuth2 flows with Google, Apple, and Facebook must continue to work

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

### Core Dependencies

From `requirements.txt`:
```
gunicorn==23.0.0
Flask==2.3.2
Authlib==1.6.6
firebase-admin==6.7.0
redis==4.4.4
google-cloud-ndb==2.3.2
google-cloud-logging==3.11.4
google-cloud-secret-manager==2.23.2
Flask-Cors==6.0.0
Pillow
```

### GAE-Specific Features in Use

| Feature | Location | Migration Impact |
|---------|----------|------------------|
| `GAE_VERSION` env var | `main.py:87` | Cache busting replacement needed |
| `GAE_INSTANCE` env var | `main.py:88` | Logging/diagnostics |
| `/_ah/start` handler | `main.py:246` | Container startup hook |
| `/_ah/warmup` handler | `main.py:255` | Health check / readiness probe |
| `/_ah/stop` handler | `main.py:265` | Graceful shutdown |
| VPC Access Connector | `app-netskrafl.yaml:29` | Network configuration |
| Static file handlers | `app-netskrafl.yaml:43-194` | Nginx/CDN replacement |
| Cron jobs | `cron.yaml` | Cloud Scheduler / platform cron |

### Cron Jobs

Current scheduled tasks (from `cron.yaml`):

| Job | Endpoint | Schedule |
|-----|----------|----------|
| Skrafl stats | `/stats/run` | Daily at 03:00 |
| Skrafl ratings | `/stats/ratings` | Daily at 03:45 |
| Online users sync | `/connect/update` | Every 2 minutes |

These endpoints check for GAE/Cloud Scheduler headers before executing:
```python
# From firebase.py:426-432
task_queue = headers.get("X-AppEngine-QueueName", "") != ""
cron_job = headers.get("X-Appengine-Cron", "") == "true"
cloud_scheduler = request.environ.get("HTTP_X_CLOUDSCHEDULER", "") == "true"
```

---

## Easy Migration Areas

### 1. Flask + Gunicorn (Already Portable)

The application is already configured to run with Gunicorn:
```bash
gunicorn -b :$PORT -w 3 --threads 6 --worker-class=gthread main:app
```

This works identically in Docker with no modifications.

### 2. Google Cloud Client Libraries

All Google Cloud services are accessed via standard client libraries that work anywhere with proper credentials:

- **NDB** (`google-cloud-ndb`): Uses `Client.get_context()` pattern
- **Secret Manager** (`google-cloud-secret-manager`): HTTP or gRPC client
- **Logging** (`google-cloud-logging`): Optional, can fall back to stdout

### 3. Firebase Admin SDK

Firebase initialization is already credential-agnostic:
```python
# From firebase.py:91-98
_firebase_app = initialize_app(
    options=dict(projectId=PROJECT_ID, databaseURL=FIREBASE_DB_URL)
)
```

Works with service account credentials or Application Default Credentials.

### 4. Redis Caching

Redis is already externalized with environment variable configuration:
```python
# From cache.py:148-149
redis_host = redis_host or os.environ.get("REDISHOST", "localhost")
redis_port = redis_port or int(os.environ.get("REDISPORT", 6379))
```

### 5. OAuth Authentication

OAuth flows use standard Authlib library with configurable endpoints:
```python
# From config.py:125
DEFAULT_OAUTH_CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"
```

No GAE-specific dependencies.

---

## Challenges Requiring Attention

### 1. GAE_VERSION Cache Busting

**Current behavior** (`main.py:223-243`):
```python
if GAE_VERSION:
    values[param_name] = GAE_VERSION
else:
    values[param_name] = int(os.stat(filepath).st_mtime)
```

**Solution**: Create a build-time version identifier:
- Option A: Git commit hash (`git rev-parse --short HEAD`)
- Option B: Build timestamp
- Option C: Docker image tag passed as environment variable

**Recommendation**: Use `APP_VERSION` environment variable set during Docker build/deployment.

### 2. Lifecycle Handlers (`/_ah/*`)

**Current handlers:**
- `/_ah/start`: Log instance startup
- `/_ah/warmup`: Load DAWG vocabularies (~10MB per language)
- `/_ah/stop`: Log shutdown

**Adaptation:**
- `/health/ready`: Kubernetes readiness probe, calls `Wordbase.warmup()`
- `/health/live`: Kubernetes liveness probe (simple 200 OK)
- Container `ENTRYPOINT` script for startup logging
- `SIGTERM` handler for graceful shutdown logging

### 3. Cron Job Replacement

**Current**: GAE cron.yaml triggers HTTP requests with special headers.

**Solutions by platform:**

| Platform | Solution |
|----------|----------|
| Cloud Run | Cloud Scheduler with authenticated requests |
| Kubernetes | CronJob resources with internal service calls |
| Digital Ocean | DO Functions / external cron service |
| Generic | Supercronic inside container or external scheduler |

**Security consideration**: Current code checks for `X-Appengine-Cron` header. Need to implement alternative authentication:
- Secret token in header
- IP allowlist
- Service account authentication

### 4. Static File Serving

**Current**: GAE serves static files directly with configurable caching.

**Options:**
1. **Gunicorn/Flask serves static** (simplest, higher latency)
2. **Nginx sidecar** (better performance)
3. **CDN** (best for production - CloudFlare, Fastly, Cloud CDN)
4. **Object storage** (GCS, S3 with CDN)

**Recommendation**: Phase 1 uses Flask for simplicity. Phase 3 adds CDN.

### 5. Environment Detection

**Current** (`authmanager.py:39-42`):
```python
running_local: bool = (
    os.environ.get("SERVER_SOFTWARE", "").startswith("Development")
    or os.environ.get("RUNNING_LOCAL", "").lower() in ("1", "true", "yes")
)
```

**Adaptation**: Set `RUNNING_LOCAL=false` explicitly in production Docker environments. The existing `RUNNING_LOCAL` override already handles this.

### 6. Logging Configuration

**Current**: Uses Google Cloud Logging in production, local logging in development.

**Adaptation**: Google Cloud Logging works outside GAE. For non-GCP platforms, configure standard Python logging to stdout (12-factor app style).

---

## Potential Showstoppers Assessment

### 1. Redis Connectivity from Non-GCP Platforms

**Risk**: HIGH for non-GCP deployments

**Current setup**: Redis (Memorystore) accessed via VPC connector at `10.128.0.3:6379`.

**Challenges:**
- Memorystore doesn't support public IP access
- VPC peering required for non-GCP access

**Mitigations:**
- **Cloud Run (same GCP project)**: VPC connector continues to work
- **External platforms**: Options include:
  - Redis Enterprise Cloud (multi-cloud)
  - Upstash (serverless Redis with HTTPS)
  - Self-managed Redis with TLS
  - Migration to platform-native caching

**Verdict**: Not a showstopper - requires Redis infrastructure decision for non-GCP.

### 2. Cold Start Performance (Vocabulary Loading)

**Risk**: MEDIUM

**Current warmup** (`wordbase.py`): Loads multiple DAWG files:
- Netskrafl: 3 Icelandic dictionaries
- Explo: 15 dictionaries (5 languages × 3 difficulty levels)

**Measured impact**: Several seconds of startup time.

**Mitigations:**
- Kubernetes: Use `startupProbe` with longer initial delay
- Cloud Run: Configure minimum instances (1+)
- General: Readiness probe fails until vocabularies loaded

**Verdict**: Not a showstopper - manageable with proper probe configuration.

### 3. Network Latency to Firebase from Non-GCP Regions

**Risk**: LOW-MEDIUM

**Impact areas:**
- Real-time presence updates
- Push notifications
- Custom token generation

**Mitigations:**
- Firebase is globally distributed
- Most operations are async and latency-tolerant
- Critical path (game moves) doesn't directly use Firebase

**Verdict**: Not a showstopper - monitor latency, acceptable for most deployments.

### 4. Google Cloud NDB Access

**Risk**: LOW

NDB client library works anywhere with:
- Service account credentials (JSON file or workload identity)
- Network access to `datastore.googleapis.com`

**Verdict**: Not a showstopper.

### 5. Secret Manager Access

**Risk**: LOW

Same as NDB - works with proper credentials and network access.

**Verdict**: Not a showstopper.

---

## Implementation Phases

### Phase 1: Dockerfile and Local Development

**Goal**: Run the application in Docker locally with docker-compose.

**Deliverables:**
- Multi-stage Dockerfile
- docker-compose.yml with Redis service
- Health check endpoints
- Local development documentation

**Timeline**: Foundation work

### Phase 2: Cloud Run Deployment

**Goal**: Deploy to Cloud Run with minimal changes.

**Deliverables:**
- Cloud Run service configuration
- VPC connector setup (reuse existing)
- Cloud Scheduler for cron jobs
- CI/CD pipeline (Cloud Build or GitHub Actions)

**Advantages**: Cloud Run handles HTTPS, scaling, and integrates with existing GCP infrastructure.

### Phase 3: Production Hardening

**Goal**: Optimize for production workloads.

**Deliverables:**
- CDN configuration for static assets
- Monitoring and alerting setup
- Auto-scaling policies
- Database connection pooling optimization
- Load testing results

### Phase 4: Multi-Platform Support

**Goal**: Enable deployment on Digital Ocean, AWS, or self-hosted Kubernetes.

**Deliverables:**
- Kubernetes manifests (Deployment, Service, Ingress, CronJob)
- Helm chart (optional)
- Platform-specific Redis configuration
- Documentation for each platform

---

## Technical Specifications

### Dockerfile (Multi-Stage Build)

```dockerfile
# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/
COPY static/ ./static/
COPY resources/ ./resources/
COPY templates/ ./templates/

# Create non-root user (optional, recommended)
# RUN useradd -m appuser && chown -R appuser:appuser /app
# USER appuser

# Environment variables (defaults, override at runtime)
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health/live || exit 1

# Expose port
EXPOSE ${PORT}

# Start application
CMD ["gunicorn", "-b", ":8080", "-w", "3", "--threads", "6", \
     "--worker-class=gthread", "--keep-alive", "10", "--timeout", "30", \
     "--pythonpath", "./src", "main:app"]
```

### docker-compose.yml (Local Development)

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - PROJECT_ID=netskrafl
      - RUNNING_LOCAL=true
      - REDISHOST=redis
      - REDISPORT=6379
      - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
      - APP_VERSION=local-dev
    volumes:
      - ./credentials:/app/credentials:ro
      - ./src:/app/src:ro  # Hot reload (development only)
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

volumes:
  redis-data:
```

---

## Local Development with Scaled Instances

Docker Compose makes it straightforward to run multiple backend instances sharing a single Redis container. This closely mirrors the production architecture where multiple GAE/Cloud Run instances share Memorystore.

### How It Works

Docker Compose creates a private network where:
1. Service names (`redis`, `app`) automatically resolve to container IPs
2. All `app` instances can reach Redis at `redis:6379`
3. A single Redis container serves all backend instances

### Scaled docker-compose.yml

```yaml
version: '3.8'

services:
  # Nginx load balancer (optional but recommended for scaled setup)
  nginx:
    image: nginx:alpine
    ports:
      - "8080:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - app

  app:
    build: .
    # Don't expose ports directly - nginx handles incoming traffic
    expose:
      - "8080"
    environment:
      - PROJECT_ID=netskrafl
      - RUNNING_LOCAL=true
      - REDISHOST=redis
      - REDISPORT=6379
      - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
      - APP_VERSION=local-dev
    volumes:
      - ./credentials:/app/credentials:ro
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      replicas: 3  # Run 3 backend instances

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"  # Expose for debugging; remove in production
    volumes:
      - redis-data:/data
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  redis-data:
```

### Nginx Configuration (`nginx.conf`)

```nginx
events {
    worker_connections 1024;
}

http {
    upstream backend {
        # Docker's internal DNS resolves 'app' to all container IPs
        server app:8080;
    }

    server {
        listen 80;

        location / {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Health check endpoint for the load balancer itself
        location /nginx-health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }
    }
}
```

### Running Scaled Instances

```bash
# Start with 3 backend instances (as configured in deploy.replicas)
docker-compose up -d

# Or override replica count at runtime
docker-compose up -d --scale app=5

# View running containers
docker-compose ps

# View logs from all app instances
docker-compose logs -f app

# View logs from a specific instance
docker-compose logs -f app-1
```

### Architecture Diagram

```
                    ┌─────────────┐
                    │   Client    │
                    └──────┬──────┘
                           │ :8080
                    ┌──────▼──────┐
                    │    Nginx    │
                    │ (optional)  │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │   App #1    │ │   App #2    │ │   App #3    │
    │  (Gunicorn) │ │  (Gunicorn) │ │  (Gunicorn) │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
                    ┌──────▼──────┐
                    │    Redis    │
                    │  (shared)   │
                    └─────────────┘
```

### Key Points

- **Single Redis instance**: All app containers connect to the same Redis. No clustering or replication needed for development.
- **Automatic service discovery**: Docker's internal DNS resolves `redis` to the Redis container's IP.
- **Stateless backends**: Each app instance is identical; Redis provides shared state.
- **Easy scaling**: Change `replicas` or use `--scale` to add/remove instances.
- **Load balancing**: Nginx distributes requests; without it, use Docker's built-in round-robin DNS.

---

## Redis Architecture by Platform

The Redis setup differs significantly between platforms:

### Cloud Run (GCP)

Cloud Run **does not support** docker-compose or sidecar containers for Redis. Each Cloud Run service scales independently.

**Redis options for Cloud Run:**

| Option | Pros | Cons |
|--------|------|------|
| **Memorystore** (current) | Managed, low latency, VPC integration | GCP-only, requires VPC connector |
| **Upstash** | Serverless, HTTP API, no VPC needed | Higher latency, pay-per-request |
| **Redis on Compute Engine** | Full control, persistent | Self-managed, single point of failure |

**Recommendation**: Continue using Memorystore for Cloud Run. The existing VPC connector (`vpc0c`) works unchanged.

```yaml
# Cloud Run service.yaml (partial)
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: netskrafl
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/vpc-access-connector: projects/netskrafl/locations/us-central1/connectors/vpc0c
    spec:
      containers:
        - image: gcr.io/netskrafl/backend:latest
          env:
            - name: REDISHOST
              value: "10.128.0.3"  # Memorystore IP
            - name: REDISPORT
              value: "6379"
```

### Self-Hosted / VMs (Digital Ocean, AWS EC2, bare metal)

Docker Compose with shared Redis works perfectly. This is ideal for:
- Development environments
- Staging servers
- Cost-sensitive production deployments
- Single-server deployments

```bash
# On a Digital Ocean Droplet or EC2 instance
docker-compose up -d --scale app=3
```

### Kubernetes (GKE, EKS, DO Kubernetes)

Redis runs as a separate Deployment/StatefulSet, accessed via a Service:

```yaml
# redis-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          args: ["--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  selector:
    app: redis
  ports:
    - port: 6379
```

Backend pods connect via `redis:6379` (service DNS name).

### Summary Table

| Platform | Redis Solution | Shared State? | Notes |
|----------|---------------|---------------|-------|
| Local dev | Docker container | Yes | docker-compose handles networking |
| Cloud Run | Memorystore | Yes | Via VPC connector |
| Digital Ocean Droplet | Docker container | Yes | Same docker-compose as local |
| DO Kubernetes | K8s Deployment | Yes | Service provides DNS |
| GKE | Memorystore or K8s | Yes | Can use either |
| AWS ECS/Fargate | ElastiCache | Yes | Managed Redis |

### Health Check Endpoints

Add to `main.py` or create `health.py`:

```python
from flask import Blueprint

health_blueprint = Blueprint('health', __name__, url_prefix='/health')

@health_blueprint.route('/live')
def liveness():
    """Kubernetes liveness probe - is the process running?"""
    return 'OK', 200

@health_blueprint.route('/ready')
def readiness():
    """Kubernetes readiness probe - is the app ready to serve traffic?"""
    # Check that vocabularies are loaded
    from wordbase import Wordbase
    if not Wordbase.is_initialized():
        return 'Warming up', 503
    # Optionally check Redis connectivity
    try:
        from cache import memcache
        memcache.get_redis_client().ping()
    except Exception:
        return 'Redis unavailable', 503
    return 'OK', 200
```

### Environment Variable Mapping

| GAE Variable | Docker Variable | Notes |
|--------------|-----------------|-------|
| `GAE_VERSION` | `APP_VERSION` | Set during build/deploy |
| `GAE_INSTANCE` | `HOSTNAME` | Auto-set by container runtime |
| `PORT` | `PORT` | Same |
| `PROJECT_ID` | `PROJECT_ID` | Same |
| `REDISHOST` | `REDISHOST` | Same |
| `REDISPORT` | `REDISPORT` | Same |
| - | `GOOGLE_APPLICATION_CREDENTIALS` | Path to service account JSON |
| - | `RUNNING_LOCAL` | Set `false` in production |

### Credential Handling Options

1. **Service Account JSON file** (local development, some platforms):
   ```bash
   docker run -v /path/to/creds.json:/app/creds.json \
     -e GOOGLE_APPLICATION_CREDENTIALS=/app/creds.json \
     myapp
   ```

2. **Workload Identity** (GKE, Cloud Run):
   - No credential file needed
   - Configure service account binding

3. **Environment variable** (some CI/CD):
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS_JSON=$(cat creds.json | base64)
   # App decodes and writes to temp file at startup
   ```

### Code Changes Required

#### 1. Cache busting update (`main.py`)

```python
# Replace GAE_VERSION lookup
APP_VERSION: str = os.environ.get("APP_VERSION", os.environ.get("GAE_VERSION", ""))
if not APP_VERSION and not running_local:
    # Fallback: use container hostname or generate random
    APP_VERSION = os.environ.get("HOSTNAME", "")[:8] or "unknown"
```

#### 2. Add health endpoints (`main.py`)

```python
from health import health_blueprint
app.register_blueprint(health_blueprint)
```

#### 3. Cron authentication update (`firebase.py`)

```python
# Add token-based authentication for external schedulers
import os
CRON_SECRET = os.environ.get("CRON_SECRET", "")

def is_cron_request() -> bool:
    """Check if request is from an authorized scheduler"""
    headers = request.headers
    # Existing GAE checks
    if headers.get("X-AppEngine-QueueName"):
        return True
    if headers.get("X-Appengine-Cron") == "true":
        return True
    if request.environ.get("HTTP_X_CLOUDSCHEDULER") == "true":
        return True
    # New: Token-based auth for external schedulers
    if CRON_SECRET and headers.get("X-Cron-Secret") == CRON_SECRET:
        return True
    # Development mode
    if running_local:
        return True
    return False
```

---

## Verification Checklist

### Pre-Migration Testing

- [ ] All existing tests pass
- [ ] Docker image builds successfully
- [ ] Local docker-compose environment works
- [ ] Health endpoints respond correctly
- [ ] Vocabularies load during warmup
- [ ] Redis connectivity works
- [ ] Firebase operations work (presence, notifications)
- [ ] OAuth login flows work
- [ ] Game creation and moves work
- [ ] Static files are served with correct headers

### Post-Migration Testing

- [ ] Cloud Run deployment succeeds
- [ ] Cloud Scheduler triggers cron endpoints
- [ ] Production traffic handles correctly
- [ ] Logging appears in Cloud Logging
- [ ] Error rates are acceptable
- [ ] Response times are comparable to GAE
- [ ] Auto-scaling works as expected

---

## Risk Summary

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Redis connectivity (non-GCP) | High | Medium | Use managed Redis service |
| Cold start latency | Medium | High | Min instances, proper probes |
| Firebase latency (non-GCP) | Low | Medium | Monitor, mostly async |
| Static file performance | Low | Medium | Add CDN in Phase 3 |
| Cron job authentication | Low | Low | Token-based auth |

---

## Conclusion

Dockerizing the Netskrafl/Explo backend is **feasible with moderate effort**. The application already uses standard Python patterns and externalized services. The main work involves:

1. Creating Docker infrastructure (Dockerfile, compose, health checks)
2. Adapting GAE-specific code (`GAE_VERSION`, lifecycle handlers)
3. Configuring cron job authentication
4. Testing thoroughly before production deployment

No showstoppers have been identified. Redis connectivity for non-GCP platforms requires infrastructure decisions but is not a blocker for Cloud Run deployment.

The phased approach allows incremental migration with minimal risk, starting with Cloud Run (closest to GAE) before expanding to other platforms.
