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

## Testing

```bash
pytest
pytest --cov=renew_website
```

## Troubleshooting

*   **Redis/WebSocket issues**: ensure Redis is running and the Channels layer is configured correctly.
*   **Database issues**: verify your `.env` or local database configuration before running migrations.
*   **Logs**: inspect `logs/` and `docker compose logs -f` when running in containers.

## License

This project is part of the "RENEW" research initiative.
