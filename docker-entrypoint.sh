#!/bin/bash
# Docker entrypoint script for Netskrafl/Explo
# Starts supercronic (cron scheduler) and gunicorn (web server)

set -e

# Apply database schema migrations when running the PostgreSQL backend.
# For a database whose schema predates Alembic (created via
# Base.metadata.create_all()), run `alembic stamp head` once manually
# before deploying with this entrypoint.
if [ "$DATABASE_BACKEND" = "postgresql" ]; then
    echo "Applying database migrations (alembic upgrade head)..."
    (cd /app && python -m alembic upgrade head)
fi

# Start supercronic in the background if CRON_SECRET is set and supercronic is installed
if [ -n "$CRON_SECRET" ] && command -v supercronic >/dev/null 2>&1; then
    echo "Starting supercronic scheduler..."
    supercronic /app/crontab &
elif [ -n "$CRON_SECRET" ]; then
    echo "Warning: CRON_SECRET set but supercronic not installed, skipping cron scheduler"
else
    echo "CRON_SECRET not set, skipping cron scheduler"
fi

# Start gunicorn in the foreground
# Settings match app-netskrafl.yaml: 3 workers, 6 threads each, gthread worker class
exec gunicorn \
    --bind "0.0.0.0:${PORT:-8080}" \
    --workers 3 \
    --threads 6 \
    --worker-class gthread \
    --keep-alive 10 \
    --timeout 30 \
    --access-logfile - \
    --access-logformat '%(h)s %(t)s "%(r)s" %(s)s %(b)s %(D)sμs' \
    --error-logfile - \
    --capture-output \
    main:app
