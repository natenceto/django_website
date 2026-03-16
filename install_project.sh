#!/bin/bash

# RENEW Project Installation Script
# This script handles the initial setup, dependency installation, database migration, and superuser creation.

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== RENEW EV Charging Platform Installation ===${NC}"

# 1. Check for Python 3.10+
echo -e "\n${YELLOW}[1/6] Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3.10+${NC}"
    exit 1
fi
python3 --version

# 2. Virtual Environment Setup
echo -e "\n${YELLOW}[2/6] Setting up Virtual Environment...${NC}"
if [ -d ".venv" ]; then
    echo "Virtual environment already exists."
else
    echo "Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate
echo "Virtual environment activated."

# 3. Install Dependencies
echo -e "\n${YELLOW}[3/6] Installing Dependencies...${NC}"
pip install --upgrade pip
if [ -f "requirements/prod.txt" ]; then
    echo "Installing production requirements..."
    pip install -r requirements/prod.txt
    
    # Check if dev requirements exist and offer to install
    if [ -f "requirements/dev.txt" ]; then
        pip install -r requirements/dev.txt
    fi
else
    echo -e "${RED}Error: requirements/prod.txt not found!${NC}"
    exit 1
fi

# 4. Environment Configuration
echo -e "\n${YELLOW}[4/6] Configuring Environment (.env)...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo -e "${GREEN}.env file created. Please update it with your real configuration later.${NC}"
    else
        echo -e "${RED}Warning: .env.example not found. Please create .env manually.${NC}"
    fi
else
    echo ".env file already exists. Skipping."
fi

# 5. Database Migrations
echo -e "\n${YELLOW}[5/6] Applying Database Migrations...${NC}"
python manage.py makemigrations
python manage.py migrate

# 6. Create Superuser
echo -e "\n${YELLOW}[6/6] Creating Administrative User (Superuser)...${NC}"
echo "You will be prompted to enter a username, email, and password."
echo "If you want to skip this step, press Ctrl+C."
python manage.py createsuperuser || true

echo -e "\n${GREEN}=== Installation Complete! ===${NC}"
echo -e "You can now start the server using:"
echo -e "  ${YELLOW}./start_server.sh${NC}"
