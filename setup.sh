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

# 2. Check for Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker and Docker Compose."
    exit 1
fi

COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
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
