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

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start the application
echo "Starting application with command: $@"
exec "$@"
