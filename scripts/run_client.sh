y#!/bin/bash

# Configuration for different environments
# Set the appropriate OCPP_SERVER_HOST before running

echo "Starting OCPP client for charging stations..."
echo "Using server: $OCPP_SERVER_HOST"

if [ -z "$OCPP_SERVER_HOST" ]; then
    echo "Warning: OCPP_SERVER_HOST not set, using default (192.168.88.243)"
    export OCPP_SERVER_HOST="192.168.88.243"
fi

# Set database connection for local client simulation against Docker DB
# Note: POSTGRES_PORT must match the host port mapped in docker-compose.yml
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5433
export POSTGRES_DB=renew_db
export POSTGRES_USER=renew_user
export POSTGRES_PASSWORD=changeme

# Make sure we are in the project root
cd "$(dirname "$0")/.."

# Run the client as a module to handle imports correctly
python -m renew_website.apps.charging_stations.client
