#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Function to test postgres connection
postgres_ready() {
    python << END
import sys
import psycopg
try:
    psycopg.connect(
        dbname="${POSTGRES_DB}",
        user="${POSTGRES_USER}",
        password="${POSTGRES_PASSWORD}",
        host="${POSTGRES_HOST}",
        port="${POSTGRES_PORT}"
    )
except psycopg.OperationalError:
    sys.exit(-1)
sys.exit(0)
END
}

echo "Waiting for PostgreSQL..."
until postgres_ready; do
  >&2 echo "PostgreSQL is unavailable - sleeping"
  sleep 1
done
echo "PostgreSQL is up - continuing"

RUN_DB_MIGRATIONS="${RUN_DB_MIGRATIONS:-0}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-0}"
DJANGO_SUPERUSER_CREATE="${DJANGO_SUPERUSER_CREATE:-0}"

if [ "$RUN_DB_MIGRATIONS" = "1" ]; then
    echo "Applying database migrations..."
    python manage.py migrate
else
    echo "Skipping database migrations (RUN_DB_MIGRATIONS=$RUN_DB_MIGRATIONS)"
fi

if [ "$RUN_COLLECTSTATIC" = "1" ]; then
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
else
    echo "Skipping static collection (RUN_COLLECTSTATIC=$RUN_COLLECTSTATIC)"
fi

if [ "$DJANGO_SUPERUSER_CREATE" = "1" ]; then
    echo "Running non-interactive superuser bootstrap..."
    python setup_superuser.py
else
    echo "Skipping automatic superuser bootstrap (DJANGO_SUPERUSER_CREATE=$DJANGO_SUPERUSER_CREATE)"
fi

# Start the application
echo "Starting application with command: $@"
exec "$@"
