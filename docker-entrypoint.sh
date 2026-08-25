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

# Start the GoSkrafl 'moves' sidecar in the background if MOVES_SIDECAR_PORT
# is set and the binary is installed. The Flask app then reaches it at
# http://127.0.0.1:$MOVES_SIDECAR_PORT (see MOVES_SERVICE_URL in src/config.py).
# No ACCESS_KEY is set: the sidecar is only reachable within the container's
# network namespace (the platform routes external traffic to gunicorn's port
# only), and the fronting Flask routes perform real session authentication.
if [ -n "$MOVES_SIDECAR_PORT" ] && command -v goskrafl-server >/dev/null 2>&1; then
    echo "Starting GoSkrafl moves sidecar on port ${MOVES_SIDECAR_PORT}..."
    (
        while true; do
            PORT="$MOVES_SIDECAR_PORT" ACCESS_KEY="" goskrafl-server
            echo "GoSkrafl sidecar exited (status $?); restarting in 2s..."
            sleep 2
        done
    ) &
elif [ -n "$MOVES_SIDECAR_PORT" ]; then
    echo "Warning: MOVES_SIDECAR_PORT set but goskrafl-server not installed, skipping moves sidecar"
else
    echo "MOVES_SIDECAR_PORT not set, skipping moves sidecar"
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
