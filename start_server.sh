#!/bin/bash

# Django EV Charging Platform - Server Startup Script
# This script starts the ASGI server with WebSocket support for OCPP

echo "=== RENEW EV Charging Platform Server ==="

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found!"
    echo "Please copy .env.example to .env and configure it:"
    echo "   cp .env.example .env"
    echo ""
    echo "Using default configuration for development..."
fi

# Activate virtual environment
PYTHON_EXEC="python"
if [ -d "venv" ]; then
    echo "Activating venv virtual environment..."
    source venv/bin/activate
    PYTHON_EXEC="./venv/bin/python"
elif [ -d ".venv" ]; then
    echo "Activating .venv virtual environment..."
    source .venv/bin/activate
    PYTHON_EXEC="./.venv/bin/python"
else
    echo "No virtual environment found!"
    echo "Create one with: python -m venv .venv"
    exit 1
fi

# Set Django settings module
export DJANGO_SETTINGS_MODULE=renew_website.settings
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Check if required packages are installed
echo "Checking dependencies..."
$PYTHON_EXEC -c "import django, channels, ocpp" 2>/dev/null || {
    echo "Missing required packages!"
    echo "Install with: $PYTHON_EXEC -m pip install -r requirements/dev.txt"
    exit 1
}

# Run database migrations if needed
echo "Checking database migrations..."
$PYTHON_EXEC manage.py migrate --check 2>/dev/null || {
    echo "Running database migrations..."
    $PYTHON_EXEC manage.py migrate
}

# Start the ASGI server
echo "Starting ASGI server with WebSocket support..."
echo "WebSocket endpoint: ws://localhost:8000/ws/charging_stations/{station_id}/"
echo "Web interface: http://localhost:8000"
echo "Press Ctrl+C to stop the server"
echo ""

# Start uvicorn with WebSocket configuration
<<<<<<< Updated upstream
uvicorn renew_website.asgi:application \
    --host 0.0.0.0 \
=======
$PYTHON_EXEC -m uvicorn renew_website.asgi:application \
    --host localhost \
>>>>>>> Stashed changes
    --port 8000 \
    --reload \
    --ws-ping-interval 60 \
    --ws-ping-timeout 60 \
    --log-level info