#!/bin/bash

# Configuration for different environments
# Set the appropriate OCPP_SERVER_HOST before running

echo "Starting OCPP client for charging stations..."
echo "Using server: $OCPP_SERVER_HOST"

if [ -z "$OCPP_SERVER_HOST" ]; then
    echo "Warning: OCPP_SERVER_HOST not set, using default (127.0.0.1)"
    export OCPP_SERVER_HOST="127.0.0.1"
fi

python renew_website/apps/charging_stations/client.py