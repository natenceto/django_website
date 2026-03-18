#!/bin/bash

# RENEW Project Installation Script (Docker Version)

echo "=== RENEW EV Charging Platform Installation (Docker) ==="

# 1. Environment Setup
if [ ! -f .env ]; then
    echo "Creating .env file from example..."
    cp .env.example .env
    echo ".env file created. Please update it with your configuration if needed."
else
    echo ".env file already exists."
fi

# 1.5 Python Local IDE Environment (Optional but recommended for VS Code)
if [ ! -d ".venv" ] && command -v python3 &> /dev/null; then
    echo "Creating local Python virtual environment for IDE support (VS Code)..."
    python3 -m venv .venv
    echo "Installing dev requirements..."
    source .venv/bin/activate && pip install -r requirements/dev.txt || true
    deactivate
elif [ -d ".venv" ]; then
    echo "Local virtual environment already exists. Updating packages..."
    source .venv/bin/activate && pip install -r requirements/dev.txt || true
    deactivate
fi

# 2. Check for Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker and Docker Compose."
    exit 1
fi

DOCKER_CMD="docker"
if ! docker info > /dev/null 2>&1; then
    echo "Docker permissions issue detected. Falling back to 'sudo docker'."
    DOCKER_CMD="sudo docker"
fi

COMPOSE_CMD=""
if $DOCKER_CMD compose version > /dev/null 2>&1; then
    COMPOSE_CMD="$DOCKER_CMD compose"
elif command -v docker-compose > /dev/null 2>&1; then
    if [[ "$DOCKER_CMD" == *"sudo"* ]]; then
        COMPOSE_CMD="sudo docker-compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
else
    echo "Error: Docker Compose is not installed."
    exit 1
fi
echo "Using Docker Compose command: $COMPOSE_CMD"

# 3. Build & Run
echo "Building and starting containers..."
$COMPOSE_CMD up --build -d

echo ""
echo "=== Create Admin User ==="
echo "If this is your first time, you need a superuser to access the admin panel."
echo "If you already have a superuser, you can skip this step."
read -p "Do you want to create a superuser now? (y/n) " create_admin

if [[ "$create_admin" =~ ^[Yy]$ ]]; then
    echo "Waiting for database to be ready..."
    sleep 5
    $COMPOSE_CMD exec web python manage.py createsuperuser
else
    echo "Skipping superuser creation."
fi

echo ""
echo "=== Installation Complete ==="
echo "Access the application at: http://localhost:8000"
echo "To follow logs: $COMPOSE_CMD logs -f"
echo "To stop: $COMPOSE_CMD down"
