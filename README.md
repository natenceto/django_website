# RENEW

RENEW is a Django-based EV charging platform with OCPP 1.6J communication, PostgreSQL persistence, Redis-backed realtime delivery, Celery background tasks, charging analytics, and Deye energy integrations.

The project title is: Research and development of a smart energy system for eco-charging of electric vehicles, using renewable energy sources.

## Access Policy

The project is intentionally restricted to these access hosts only:

- `localhost`
- `127.0.0.1`
- `192.168.88.247`

Do not add other public hosts unless you intentionally broaden the deployment model.

## Stack and Versions

### Protocol and Runtime

- OCPP profile: OCPP 1.6J (JSON over WebSocket; subprotocol `OCPP1.6`/`ocpp1.6`)
- Python: `3.12` (container base image)
- Django: `5.2`
- Docker Compose: V2

### Infrastructure Containers

- PostgreSQL: `15-alpine`
- Redis: `7-alpine`
- Nginx (production compose): `1.25-alpine`

### Production Python Dependencies

- Django: `5.2`
- psycopg: `3.2.10`
- python-dotenv: `1.1.1`
- channels: `4.3.1`
- channels-redis: `4.2.1`
- daphne: `>=4.1.0`
- uvicorn: `0.37.0`
- gunicorn: `>=21.2.0`
- websockets: `13.1`
- ocpp: `0.17.0`
- whitenoise: `6.11.0`
- django-environ: `0.12.0`
- jsonschema: `4.4.0`
- redis (Python client): `5.2.1`
- djangorestframework: `3.15.2`
- django-filter: `24.3`
- drf-spectacular: `0.28.0`
- djangorestframework-simplejwt: `5.4.0`
- django-cors-headers: `4.6.0`
- requests: `>=2.31.0`
- user-agents: `>=2.2.0`
- deye-controller: `0.2.3`
- pyserial: `3.5`
- pysolarmanv5: `3.0.6`
- umodbus: `1.0.4`
- celery: `>=5.3.6`
- django-celery-beat: `>=2.5.0`
- django-celery-results: `>=2.5.0`
- flower: `2.0.1`
- hiredis: `>=2.3.2`
- pymodbus: `3.12.1`

### Development Dependencies (additional)

- mypy: `1.17.0`
- black: `24.10.0`
- isort: `5.13.2`
- flake8: `7.1.1`
- django-debug-toolbar: `4.4.6`
- ipython: `8.29.0`

### Testing Dependencies

- pytest: `8.3.4`
- pytest-django: `4.9.0`
- pytest-asyncio: `0.24.0`
- pytest-cov: `6.0.0`
- factory-boy: `3.3.1`
- faker: `33.1.0`
- coverage: `7.6.9`

### Frontend Vendor Libraries

- jQuery: `3.6.0`
- Bootstrap (JS bundle): `4.6.0`
- Chart.js: `2.9.4`
- Font Awesome Free: `5.15.3`
- jQuery Easing: `1.4.1`

## First Start

Always start with `setup.sh` after cloning the project.

```bash
git clone <repository-url>
cd django_website
./setup.sh
```

`setup.sh` is the canonical bootstrap entrypoint. It does the initial preparation in the correct order:

1. Creates `.env` from `.env.example` if it is missing.
2. Creates `.venv` if it is missing.
3. Installs `requirements/dev.txt` into `.venv`.
4. Verifies Docker and Docker Compose availability.
5. Starts the local stack with `docker compose up --build -d` when Docker is available.
6. Runs `python manage.py migrate`.
7. Runs `python manage.py check`.
8. Prompts to create a superuser only when no superuser exists yet.

If you want the virtual environment active in your current shell after the script finishes:

```bash
source .venv/bin/activate
```

## Environment Configuration

The project reads configuration from `.env`. Start from `.env.example` and review at least these keys:

```env
SECRET_KEY=change-this-secret-key-in-production-keep-it-secure
DEBUG=True
ENABLE_API_DOCS=True
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.88.247
CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1,http://192.168.88.247,http://localhost:8000,http://127.0.0.1:8000,http://192.168.88.247:8000
CORS_ALLOWED_ORIGINS=http://localhost,http://127.0.0.1,http://192.168.88.247,http://localhost:8000,http://127.0.0.1:8000,http://192.168.88.247:8000
POSTGRES_DB=renew_db
POSTGRES_USER=renew_user
POSTGRES_PASSWORD=your-secure-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
REDIS_URL=redis://localhost:6379/0
USE_REDIS_CHANNEL_LAYER=True
POSTGRES_CONN_MAX_AGE=60
SECURE_SSL_REDIRECT=False
DJANGO_LOG_LEVEL=INFO
DEYE_APP_ID=your-deye-app-id
DEYE_APP_SECRET=your-deye-app-secret
DEYE_EMAIL=your-deye-account-email
DEYE_PASSWORD=your-deye-account-password
DEYE_DATACENTER=eu
DEYE_COMPANY_ID=0
OCPP_SERVER_HOST=192.168.88.243
OCPP_SERVER_PORT=8000
```

Important notes:

- `POSTGRES_PASSWORD` must be set explicitly. There is no weak fallback in Compose anymore.
- Redis is the expected backend for Channels, Celery, and cache in containerized runs.
- `REDIS_URL` is mandatory when `DEBUG=False`.
- API docs are enabled only when `ENABLE_API_DOCS=True`.
- `SECURE_SSL_REDIRECT` should stay `False` until you actually terminate TLS in front of Django.
- For browser/frontend integrations, include both HTTP and HTTPS origins where needed. The default CORS list also includes `http://localhost:3000`.
- In production-style setups, include HTTPS hosts in both `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS`.
- `DEYE_*` variables are required for DeyeCloud integrations.

## API Documentation Endpoints

When `ENABLE_API_DOCS=True`, these routes are available:

- `/api/schema/`
- `/api/docs/`
- `/api/redoc/`

## Local Docker Workflow

Use this for day-to-day development after `setup.sh` has prepared the environment:

```bash
docker compose up -d --build
docker compose logs -f web
docker compose down
```

The development stack behavior is:

- Django app on `http://localhost:8000`
- Django app also reachable on `http://192.168.88.247:8000`
- PostgreSQL published only to `127.0.0.1:5432`
- Redis published only to `127.0.0.1:6379`
- Flower published only to `127.0.0.1:5555`

## Production-Style Docker Workflow

Use the production compose file when you want Gunicorn + Nginx + restart policies:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml down
```

Current production-style behavior:

- Gunicorn runs the ASGI app with Uvicorn workers.
- Nginx listens only on `localhost:80` and `192.168.88.247:80`.
- Nginx rejects host headers outside the allowed host set.
- WebSocket traffic is rate-limited in the reverse proxy.
- API docs are disabled by default.

TLS note:

- The project is prepared for secure-cookie and proxy-aware HTTPS behavior when `DEBUG=False`.
- If you add real TLS termination, set `SECURE_SSL_REDIRECT=True` and configure certificates at the reverse proxy layer.
- Do not force HTTPS redirects before the proxy actually serves HTTPS, or you will create redirect loops or a broken deployment.

## Superuser Creation

Interactive superuser creation during `setup.sh` is the default practice for this repository.

Why:

- It avoids hardcoded credentials.
- It avoids creating admin accounts during container boot.
- It always prompts during setup so you can choose `y` or `n` each run.

If you need a non-interactive bootstrap for automation, use environment variables and run:

```bash
DJANGO_SUPERUSER_CREATE=1 \
DJANGO_SUPERUSER_USERNAME=admin \
DJANGO_SUPERUSER_EMAIL=admin@example.com \
DJANGO_SUPERUSER_PASSWORD=change-me \
python setup_superuser.py
```

The entrypoint does not auto-create superusers.

## Manual Local Workflow Without Docker

If Docker is unavailable, `./setup.sh local` prepares `.venv` and prints the local next steps.

Typical manual sequence:

```bash
./setup.sh local
source .venv/bin/activate
python manage.py migrate
python manage.py createsuperuser
python manage.py check
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000
```

For manual local runs you still need PostgreSQL and Redis running separately.

## Runtime Components

- Django serves HTTP and API traffic.
- Channels serves OCPP and browser WebSocket traffic.
- Redis backs Channels, Celery, and Django cache when configured.
- Celery worker executes background tasks.
- Celery Beat schedules periodic tasks.
- Nginx is used in the production-style stack.
- On ASGI startup, station and connector statuses are reset to avoid stale online/active state from previous runs.

## OCPP Endpoints

Charging station connections:

- `ws://localhost:8000/ws/charging_stations/{station_id}/`
- `ws://192.168.88.247:8000/ws/charging_stations/{station_id}/`

Browser status socket:

- `/ws/stations/status/`
- `/ws/station/{station_id}/`

The browser status socket now requires an authenticated Django user session.

## Schema Change Workflow

Whenever models change, use this order:

```bash
docker compose exec -T web python manage.py makemigrations
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py check
```

Do not skip `migrate` after creating migrations. This project has realtime and worker processes that assume the schema is already current.

## Validation Commands

Use these commands regularly while developing:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
pip check
```

Focused examples:

```bash
pytest renew_website/apps/charging_stations/tests/test_consumers.py -q
pytest renew_website/apps/api/tests.py -q
```

## Troubleshooting

WebSocket issues:

- Ensure Redis is running.
- Ensure the browser user is authenticated for `/ws/stations/status/`.
- Ensure the host is `localhost` or `192.168.88.247`.

Database issues:

- Verify PostgreSQL credentials in `.env`.
- Verify the database container is healthy.
- Run `python manage.py migrate`.

Celery issues:

- Verify `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND`.
- Check `docker compose logs -f celery`.
- Check `docker compose logs -f celery-beat`.

Static file issues:

- In containers, static collection is controlled by `RUN_COLLECTSTATIC`.
- In the production-style stack, Nginx serves `/static/` from the shared static volume.

## Logs

- Django app: `docker compose logs -f web`
- Celery worker: `docker compose logs -f celery`
- Celery beat: `docker compose logs -f celery-beat`
- Nginx: `docker compose -f docker-compose.prod.yml logs -f nginx`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is part of the RENEW research initiative.
