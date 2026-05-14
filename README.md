# RENEW

RENEW is a Django-based web application for managing electric vehicle charging stations and renewable energy integrations. The platform supports station management, OCPP communication, weather and energy data, and role-based administration.

The project title: Research and development of a smart Energy system for eco-charging of electric vehicles, using reNEWable energy sources.

## Features

- Station owner registration and management
- Charging station onboarding and monitoring
- OCPP 1.6 real-time communication
- Weather and solar irradiance integration
- Role-based access for administrators, station owners, and end users

## Tech Stack & Requirements

- Python 3.12+
- Django 5.2
- PostgreSQL 15+
- Redis 7+
- Docker with Docker Compose V2 for the containerized setup
- Frontend: HTML, CSS, JavaScript

## Installation

### Quick Start

1. Clone the repository:

```bash
git clone <repository-url>
cd django_website
```

2. Run the startup script before any `docker compose up --build` or manual Django commands:

```bash
./setup.sh
```

The script performs the required pre-Docker preparation automatically:

- creates `.env` from `.env.example` when missing
- creates `.venv`
- activates `.venv` for the setup process
- installs Python dependencies from `requirements/dev.txt`
- checks Docker and Docker Compose availability
- starts the containers and runs migrations when Docker is usable
- falls back to local preparation instructions when Docker is unavailable

3. If you want the virtual environment active in your current terminal after the script finishes, run:

```bash
source .venv/bin/activate
```

### What happens if Docker is not installed?

`./setup.sh` still performs the Python-side preparation and then stops before infrastructure startup. It prints the local next steps:

- install and start PostgreSQL
- install and start Redis if Channels/Celery are needed
- update `.env` for the local database host and credentials
- run `python manage.py migrate`
- run `python manage.py createsuperuser`
- start the app with `uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000 --reload`

You can also force this behavior explicitly with:

```bash
./setup.sh local
```

### Docker Setup

For normal development, prefer `./setup.sh` instead of invoking Docker directly first. If the environment is already prepared and you only need to restart services later, you can use:

```bash
docker compose up -d --build
```

For production:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Key Packages

### Core Dependencies
- `Django==5.2` - Web framework
- `psycopg==3.2.10` - PostgreSQL adapter
- `python-dotenv==1.1.1` - Environment variables

### WebSocket & Real-time
- `channels==4.3.1` - Django Channels for WebSockets
- `channels-redis==4.2.1` - Redis channel layer
- `uvicorn==0.37.0` - ASGI server
- `websockets==13.1` - WebSocket support

### OCPP Protocol
- `ocpp==0.17.0` - Open Charge Point Protocol implementation

### REST API
- `djangorestframework==3.15.2` - Django REST framework
- `drf-spectacular==0.28.0` - API documentation
- `django-cors-headers==4.6.0` - CORS support

## Usage

- Administrator can manage all aspects of the platform.  
- Station Owners can add new stations and track their station info.  
- Users can view charging sessions and history.

### OCPP WebSocket Connections

The platform supports OCPP 1.6 protocol for real-time communication with charging stations:

**WebSocket Endpoint:** `ws://your-server:8000/ws/charging_stations/{station_id}/`

**Setup Hostname (Optional):**
```bash
./setup_hostname.sh
# This adds 'renew' to /etc/hosts for local testing
```

**Example Connections:**
- `ws://localhost:8000/ws/charging_stations/1/`
- `ws://192.168.1.100:8000/ws/charging_stations/1/`
- `ws://renew:8000/ws/charging_stations/1/` (after hostname setup)

**Supported OCPP Actions:**
- BootNotification
- Heartbeat
- Authorize
- StartTransaction
- StopTransaction
- StatusNotification
- MeterValues

## Testing

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=renew_website

# Run specific test file
pytest renew_website/apps/charging_stations/tests/
```

### OCPP Simulator
For testing OCPP connections, you can use WebSocket clients or OCPP simulators to connect to the WebSocket endpoint.

## Development

### Starting the Server
```bash
# If this is the first run, prepare the environment first
./setup.sh

# Then start manually with auto-reload
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000 --reload

# Manual start
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000
```

### Schema Changes

When you change Django models or anything that affects the database schema, use this order:

```bash
docker compose exec -T web python manage.py makemigrations
docker compose exec -T web python manage.py migrate
docker compose exec -T web python manage.py check
```

- `makemigrations` detects model changes and creates migration files.
- `migrate` applies the schema changes to PostgreSQL.
- `check` validates Django configuration and model/admin consistency after the database is up to date.
- In this project, code reload can happen before migrations are applied, so skipping `migrate` after model changes can lead to runtime errors such as missing columns.

### Code Quality
```bash
# Format code
black .
isort .

# Lint
flake8 .

# Type checking
mypy .
```

## DeyeCloud API Integration

The platform integrates with DeyeCloud for energy monitoring:

1. **Install requests library:**
```bash
pip install requests
```

2. **Configure in .env:**
```bash
DEYE_APP_ID=your-deye-app-id
DEYE_APP_SECRET=your-deye-app-secret
DEYE_EMAIL=your-deye-account-email
DEYE_PASSWORD=your-deye-account-password
```

3. **Run the server** - API integration will work automatically

## Production Deployment

### Environment Variables
```bash
DEBUG=False
SECRET_KEY=your-secure-secret-key
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

### Docker Production
```bash
docker compose -f docker-compose.prod.yml up -d
```

### Static Files
```bash
python manage.py collectstatic --noinput
```

## Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**
   - Check if Redis is running
   - Verify firewall settings
   - Ensure WebSocket endpoint is correct

2. **OCPP Protocol Errors**
   - Verify OCPP version compatibility (1.6)
   - Check message format
   - Review station configuration

3. **Database Connection Issues**
   - Verify PostgreSQL is running
   - Check database credentials in .env
   - Ensure database exists

### Logs
- Application logs: `logs/django.log`
- Docker logs: `docker compose logs -f web`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is part of the RENEW research initiative.
