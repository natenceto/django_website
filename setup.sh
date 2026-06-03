#!/bin/bash

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"
COMPOSE_CMD=""

finish() {
    local code="$1"

    if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
        return "$code"
    fi

    exit "$code"
}

print_header() {
    echo "=========================================================="
    echo "   RENEW EV Charging Platform Initial Setup               "
    echo "=========================================================="
}

ensure_env_file() {
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
            echo "--> Creating .env from .env.example..."
            cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
            echo "--> .env created. Review the values before first real deployment."
        else
            echo "Warning: .env.example was not found. Skipping .env creation."
        fi
    else
        echo "--> .env already exists."
    fi
}

ensure_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Error: python3 is required to create the virtual environment."
        finish 1
    fi
}

ensure_venv() {
    ensure_python

    if [[ ! -d "$VENV_DIR" ]]; then
        echo "--> Creating virtual environment in .venv..."
        python3 -m venv "$VENV_DIR"
    else
        echo "--> Virtual environment already exists."
    fi

    echo "--> Activating virtual environment for setup commands..."
    # This activation is scoped to the current script process.
    # A child script cannot keep the parent's shell activated after it exits.
    # Users still need to run `source .venv/bin/activate` in their own shell.
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    export DJANGO_SETTINGS_MODULE=renew_website.settings
    export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

    echo "--> Installing Python dependencies..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PIP_BIN" install -r "$PROJECT_ROOT/requirements/dev.txt"
}

print_local_next_steps() {
    echo ""
    echo "=== Docker not available: local preparation completed ==="
    echo "The Python environment is ready in .venv."
    echo "Because Docker is unavailable, the script stops before starting infrastructure services."
    echo ""
    echo "To keep the virtual environment active in your current terminal, run:"
    echo "source .venv/bin/activate"
    echo ""
    echo "Local run requirements without Docker:"
    echo "1. Install and start PostgreSQL."
    echo "2. Install and start Redis if you need Channels/Celery."
    echo "3. Update .env so POSTGRES_HOST/PORT/USER/PASSWORD match your machine."
    echo "4. Run: python manage.py migrate"
    echo "5. Run: python manage.py createsuperuser"
    echo "6. Start the app: uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000"
    echo ""
    echo "If you prefer the containerized setup later, install Docker and rerun ./setup.sh."
}

resolve_compose_cmd() {
    local docker_cmd="docker"

    if ! command -v docker >/dev/null 2>&1; then
        echo "--> Docker is not installed on this machine."
        return 1
    fi

    if ! docker info >/dev/null 2>&1; then
        if command -v sudo >/dev/null 2>&1 && sudo -n docker info >/dev/null 2>&1; then
            docker_cmd="sudo docker"
        else
            echo "--> Docker is installed but the daemon is not reachable for the current user."
            echo "--> Start the Docker service or add your user to the docker group, then rerun ./setup.sh."
            return 1
        fi
    fi

    if $docker_cmd compose version >/dev/null 2>&1; then
        COMPOSE_CMD="$docker_cmd compose"
        return 0
    fi

    echo "--> Docker is installed, but Docker Compose V2 is unavailable."

    return 1
}

run_docker_setup() {
    echo "--> Building and starting Docker services..."
    (cd "$PROJECT_ROOT" && $COMPOSE_CMD up --build -d)

    echo "--> Waiting for database container to initialize..."
    sleep 5

    echo "--> Running database migrations in the web container..."
    (cd "$PROJECT_ROOT" && $COMPOSE_CMD exec -T web python manage.py migrate)

    echo "--> Running Django system checks..."
    (cd "$PROJECT_ROOT" && $COMPOSE_CMD exec -T web python manage.py check)

    local superuser_count
    superuser_count="$(cd "$PROJECT_ROOT" && $COMPOSE_CMD exec -T web python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(is_superuser=True).count())")"
    superuser_count="$(echo "$superuser_count" | tr -dc '0-9')"

    echo ""
    echo "=== Create Admin User ==="
    if [[ "${superuser_count:-0}" == "0" ]]; then
        echo "--> No superuser exists yet (first run scenario)."
    else
        echo "--> Existing superuser count: ${superuser_count}."
    fi

    echo "--> This prompt appears on every setup run."
    echo "--> Choose 'y' to start Django's interactive createsuperuser flow, or 'n' to skip."
    read -r -p "Run createsuperuser now? (y/n) " create_admin

    if [[ "$create_admin" =~ ^[Yy]$ ]]; then
        (cd "$PROJECT_ROOT" && $COMPOSE_CMD exec web python manage.py createsuperuser)
    else
        echo "Skipping superuser creation. You can run it later with:"
        echo "$COMPOSE_CMD exec web python manage.py createsuperuser"
    fi

    echo ""
    echo "=== EMS Management ==="
    echo "За да стартирате балансиращия алгоритъм в бекграунд, изпълнете:"
    echo "$COMPOSE_CMD exec -d web python manage.py run_ems"
    echo ""
    echo "=== Installation Complete ==="
    echo "Application URL: http://localhost:8000"
    echo "Logs: $COMPOSE_CMD logs -f"
    echo "Stop: $COMPOSE_CMD down"
}

main() {
    local requested_mode="auto"

    if [[ $# -gt 0 ]]; then
        requested_mode="$1"
    fi

    print_header
    cd "$PROJECT_ROOT" || finish 1

    ensure_env_file
    ensure_venv

    if [[ "$requested_mode" == "local" ]]; then
        print_local_next_steps
        finish 0
    fi

    if resolve_compose_cmd; then
        run_docker_setup
        echo ""
        echo "To activate the same virtual environment in your current terminal later, run:"
        echo "source .venv/bin/activate"
        finish 0
    fi

    print_local_next_steps
    finish 0
}

main "$@"