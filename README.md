<<<<<<< Updated upstream
# RENEW

RENEW is a Django-based web application designed for managing electric vehicle charging stations. The platform allows station owners to register, add, and manage their charging stations, while users can view information and history related to charging.

The project title: Research and development of a smart Energy system for eco-charging of 
electric vehicles, using reNEWable energy sources 

## Features

- Station owner registration and management  
- Adding and managing charging stations  
- Viewing detailed station information  
- User roles and permissions:  
  - Administrator: Full control over the platform  
  - Station Owner: Manage their own stations  
  - User: View charging information and history  

## Tech Stack & Requirements

- Python 3.12+  
- Django 5.2  
- PostgreSQL (production database)  
- Redis (for WebSocket channel layer)
- Frontend: HTML, CSS, JavaScript (with SB Admin 2 theme)
- OCPP 1.6 Protocol Support
- WebSocket Real-time Communication

## Installation

### Prerequisites
- Python 3.12+
- PostgreSQL 15+
- Redis 7+
- Node.js (for frontend development, optional)

### Quick Start

1. **Clone the repository**
```bash
git clone <repository-url>
cd django_website_copy
```

2. **Create virtual environment**
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

3. **Install dependencies**
```bash
pip install -r requirements/dev.txt
```

4. **Environment setup**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Database setup**
```bash
# For PostgreSQL (recommended)
# Create database and user as specified in .env
python manage.py migrate

# For development with SQLite (default)
python manage.py migrate
```

6. **Create superuser**
```bash
python manage.py createsuperuser
```

7. **Start the server**
```bash
# Development
./start_server.sh

# Or manually
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000 --reload
```

### Docker Setup

1. **Development with Docker**
```bash
docker-compose up -d
```

2. **Production with Docker**
```bash
docker-compose -f docker-compose.prod.yml up -d
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
# Development with auto-reload
./start_server.sh

# Manual start with reload
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000 --reload

# Manual start
uvicorn renew_website.asgi:application --host 0.0.0.0 --port 8000
```

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
docker-compose -f docker-compose.prod.yml up -d
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
- Docker logs: `docker-compose logs -f web`

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.
=======
# RENEW - Smart Energy System for EV Eco-Charging

**Full Title**: Research and development of a smart Energy system for eco-charging of electric vehicles, using reNEWable energy sources.

RENEW is a Django-based web application designed for managing electric vehicle (EV) charging stations and integrating renewable energy sources (Solar PV). The platform allows station owners to register and manage their charging stations, while users can view availability, charging history, and real-time statistics. It features full OCPP 1.6J support and integration with Deye inverters.

## Features

*   **Station Management**: Add, configure, and monitor EV charging stations.
*   **OCPP 1.6 Support**: Real-time communication with charging stations via WebSocket (OCPP 1.6J).
*   **Smart Energy Management**: Integration with Deye inverters for solar energy monitoring and optimization.
*   **User Roles**:
    *   **Administrator**: Full control over the platform, system settings, and user management.
    *   **Station Owner**: Manage owned stations and view transaction history.
    *   **User**: View charging status, availability, and session history.
*   **Dashboard & Analytics**: Visual representation of energy consumption and charging sessions.

## Tech Stack

*   **Backend**: Python 3.12+, Django 5.2
*   **Database**: PostgreSQL 15+ (Production), SQLite (Development/Auth)
*   **Async/Real-time**: Django Channels, Redis, Uvicorn (ASGI)
*   **Frontend**: HTML5, CSS3, JavaScript (Bootstrap 5 / SB Admin 2)
*   **Protocol**: OCPP 1.6 JSON

## Installation & Setup

This project handles its own setup via automated scripts.

### Prerequisites

Ensure you have the following installed on your system:
*   **Python 3.12** or higher
*   **Git**
*   **Redis** (Required for WebSocket functionality)
*   *Optional*: PostgreSQL (Recommended for production)

### 1. Clone the Repository

```bash
git clone <repository-url>
cd django_website
```

### 2. Install and Configure

We provide a comprehensive installation script that handles:
1.  Virtual environment creation (`.venv`)
2.  Dependency installation
3.  Environment configuration (`.env`)
4.  Database migrations
5.  Superuser creation (Interactive)

Run the installation script:

```bash
chmod +x install_project.sh
./install_project.sh
```

Follow the on-screen prompts. When asked, create your superuser account (admin) with a username, email, and password.

### 3. Start the Server

Once installed, start the development server:

```bash
chmod +x start_server.sh
./start_server.sh
```

This will launch:
*   **Web Interface**: [http://localhost:8000](http://localhost:8000)
*   **Admin Interface**: [http://localhost:8000/admin](http://localhost:8000/admin) (Django Admin)
*   **Portal Dashboard**: [http://localhost:8000/portal/dashboard](http://localhost:8000/portal/dashboard) (Professional Dashboard - requires staff login)
*   **WebSocket Endpoint**: `ws://localhost:8000/ws/charging_stations/{station_id}/`

## Project Structure

*   `renew_website/`: Main project configuration.
*   `renew_website/apps/`: Django applications.
    *   `accounts/`: User authentication and profiles.
    *   `admin/`: Custom admin dashboard and professional system settings.
    *   `api/`: REST API endpoints (Deye integration, Mobile App API).
    *   `charging_stations/`: OCPP logic, station management models.
    *   `public/`: Public-facing pages (Landing, About, Contact).
*   `templates/`: HTML templates.
*   `static/`: CSS, JS, and image assets.
*   `requirements/`: Python dependency lists.
*   `scripts/`: Utility scripts.

## License

This project is part of the "RENEW" research initiative.
>>>>>>> Stashed changes
