#!/bin/bash

# RENEW Project - Virtual Environment Initialization Script
# This script activates the virtual environment for development

echo "[init_venv.sh] Starting script..."

# Check if .venv directory exists
if [ ! -d ".venv" ]; then
    echo "[init_venv.sh] Virtual environment not found. Creating new one..."
    python3 -m venv .venv
    echo "[init_venv.sh] Installing dependencies..."
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements/dev.txt
else
    echo "[init_venv.sh] Virtual environment found. Activating..."
    source .venv/bin/activate
fi

# Set Django settings module
export DJANGO_SETTINGS_MODULE=renew_website.settings
export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "[init_venv.sh] Done — environment activated."
