#!/usr/bin/env bash
set -e  # Exit on error

echo "[init_venv.sh] Starting script..."

# Determine project root (portable alternative to ${workspaceFolder})
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(dirname "$script_dir")"

if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f "$project_root/.venv/bin/activate" ]; then
        source "$project_root/.venv/bin/activate"
    elif [ -f ".venv/bin/activate" ]; then
        source ".venv/bin/activate"
    else
        echo "[init_venv.sh] Virtual environment (.venv) not found."
        exit 1
    fi
fi

echo "[init_venv.sh] Done — environment activated."