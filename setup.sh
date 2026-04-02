#!/bin/bash

# RENEW Project Installation Script (Docker Version)
# Оптимизиран за EMS модула (Deye + Charging Stations)

echo "=========================================================="
echo "   RENEW EV Charging Platform Installation (Docker)    "
echo "=========================================================="

# 1. Environment Setup
if [ ! -f .env ]; then
    echo "--> Creating .env file from example..."
    cp .env.example .env
    echo "!!! .env file created. Please update it with your configuration."
else
    echo "--> .env file already exists."
fi

# 2. Python Local IDE Environment (Support for VS Code/PyCharm)
if [ ! -d ".venv" ] && command -v python3 &> /dev/null; then
    echo "--> Creating local virtual environment for IDE support..."
    python3 -m venv .venv
    echo "--> Installing requirements in .venv..."
    source .venv/bin/activate && pip install --upgrade pip && pip install -r requirements/dev.txt || true
    deactivate
elif [ -d ".venv" ]; then
    echo "--> Local virtual environment found. Updating packages..."
    source .venv/bin/activate && pip install -r requirements/dev.txt || true
    deactivate
fi

# 3. Docker & Compose Check
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed."
    exit 1
fi

DOCKER_CMD="docker"
if ! docker info > /dev/null 2>&1; then
    DOCKER_CMD="sudo docker"
fi

COMPOSE_CMD=""
if $DOCKER_CMD compose version > /dev/null 2>&1; then
    COMPOSE_CMD="$DOCKER_CMD compose"
else
    COMPOSE_CMD="docker-compose"
fi

# 4. Build & Run
echo "--> Building and starting containers (this may take a few minutes)..."
# Използваме --build за да сме сигурни, че новите библиотеки (pymodbus) се инсталират
$COMPOSE_CMD up --build -d

# 5. Database Migrations (Критично за новите Modbus полета)
echo "--> Waiting for database to be ready..."
sleep 5
echo "--> Running database migrations..."
$COMPOSE_CMD exec web python manage.py migrate

# 6. Admin User Creation
echo ""
echo "=== Create Admin User ==="
read -p "Do you want to create a superuser now? (y/n) " create_admin

if [[ "$create_admin" =~ ^[Yy]$ ]]; then
    $COMPOSE_CMD exec web python manage.py createsuperuser
else
    echo "Skipping superuser creation."
fi

# 7. EMS Background Process (Info)
echo ""
echo "=== EMS Management ==="
echo "За да стартирате балансиращия алгоритъм в бекграунд, изпълнете:"
echo "$COMPOSE_CMD exec -d web python manage.py run_ems"
echo ""

echo "=== Installation Complete ==="
echo "Application URL: http://localhost:8000"
echo "Logs: $COMPOSE_CMD logs -f"
echo "Stop: $COMPOSE_CMD down"
echo "=========================================================="