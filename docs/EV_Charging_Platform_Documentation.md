# EV Charging Platform - Професионална документация

## Версия 1.0 | Януари 2026

---

## Съдържание

1. [Въведение](#въведение)
2. [Архитектура](#архитектура)
3. [Инсталация и конфигурация](#инсталация-и-конфигурация)
4. [API документация](#api-документация)
5. [OCPP интеграция](#ocpp-интеграция)
6. [Energy Management](#energy-management)
7. [База данни](#база-данни)
8. [Security](#security)
9. [Monitoring и logging](#monitoring-и-logging)
10. [Deployment](#deployment)

---

## Въведение

### Общ преглед

EV Charging Platform е интегрирана система за управление на мрежа от електрически зарядни станции, която съчетава:

- **OCPP 1.6** протокол за комуникация със станции
- **DeyeCloud API** интеграция за соларни инвертори
- **Real-time monitoring** и управление
- **Smart charging** оптимизация
- **Billing система** с ценообразуване

### Ключови характеристики

| Характеристика | Описание |
|----------------|---------|
| **Протокол** | OCPP 1.6 (JSON over WebSocket) |
| **Енергия** | DeyeCloud инвертор интеграция |
| **База данни** | PostgreSQL + Redis |
| **Frontend** | Django Templates + Bootstrap |
| **API** | Django REST Framework |
| **Real-time** | Django Channels (WebSocket) |

### Технологичен стек

```
Backend:  Django 4.2 + Python 3.12
Frontend: Bootstrap 5 + jQuery
Database: PostgreSQL 14 + Redis 7
API:     Django REST Framework
WebSocket: Django Channels
Queue:   Redis (Celery)
```

---

## Архитектура

### Системна архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                      │
├─────────────────────────────────────────────────────────────┤
│  Web Dashboard  │  Mobile Interface  │  Admin Panel        │
│  - Real-time    │  - Charging Status │  - Station Mgmt    │
│  - Analytics    │  - User Profile    │  - Billing Admin   │
│  - Reports      │  - Payment History  │  - System Config   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP/WebSocket
┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                        │
├─────────────────────────────────────────────────────────────┤
│  Django Framework │  Channels (WebSocket) │  REST API       │
│  - Authentication │  - OCPP 1.6 Handler   │  - Station API  │
│  - Business Logic │  - Real-time Updates  │  - Energy API    │
│  - Data Validation│  - Status Broadcasting│  - Billing API   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ SQL/NoSQL
┌─────────────────────────────────────────────────────────────┐
│                      DATA LAYER                             │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL         │  Redis Cache      │  Time-Series DB   │
│  - Users/Stations   │  - Session Store   │  - Energy Data    │
│  - Transactions    │  - Real-time Cache │  - Historical     │
│  - Billing Records  │  - Message Queue   │  - Analytics      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ External APIs
┌─────────────────────────────────────────────────────────────┐
│                 EXTERNAL INTEGRATIONS                       │
├─────────────────────────────────────────────────────────────┤
│  DeyeCloud API        │  Payment Gateway   │  Energy Grid     │
│  - Inverter Data      │  - Stripe/PayPal   │  - Smart Grid    │
│  - Solar Monitoring   │  - Mobile Payments │  - V2G           │
│  - Battery Status     │  - Subscriptions   │  - Load Balancing│
└─────────────────────────────────────────────────────────────┘
```

### Модулна структура

```
django_website/
├── apps/
│   ├── charging_stations/     # OCPP и станции
│   │   ├── models.py          # Station, Transaction, ChargingSession
│   │   ├── consumers.py       # WebSocket потребители
│   │   ├── ocpp/              # OCPP модули
│   │   │   ├── registry.py    # Активни станции
│   │   │   ├── websocket.py   # WebSocket wrapper
│   │   │   └── chargepoint.py # OCPP ChargePoint
│   │   └── views.py           # Station management
│   │
│   ├── api/energy/            # Energy management
│   │   ├── models.py          # Inverter, Reading models
│   │   ├── services.py        # DeyeCloud интеграция
│   │   ├── views.py           # Energy API endpoints
│   │   └── templates/energy/   # Energy dashboard
│   │
│   ├── api/deye/              # DeyeCloud клиент
│   │   ├── client.py          # API клиент
│   │   └── views.py           # Deye API endpoints
│   │
│   ├── users/                 # User management
│   └── billing/               # Billing система
│
├── static/                    # Static assets
├── templates/                 # Django templates
└── media/                     # Media files
```

---

## Инсталация и конфигурация

### Системни изисквания

```
Python:      3.12+
Database:    PostgreSQL 14+
Cache:       Redis 7+
Memory:      4GB+ RAM
Storage:     50GB+ SSD
Network:     1Gbps+ (за WebSocket връзки)
```

### Инсталация

```bash
# 1. Клониране на репозиторито
git clone https://github.com/your-org/ev-charging-platform.git
cd ev-charging-platform

# 2. Създаване на виртуална среда
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Инсталация на зависимости
pip install -r requirements.txt

# 4. Конфигурация на база данни
createdb ev_charging_platform

# 5. Миграция на база данни
python manage.py migrate

# 6. Създаване на суперпотребител
python manage.py createsuperuser

# 7. Събиране на static файлове
python manage.py collectstatic

# 8. Стартиране на сървъра
python manage.py runserver
```

### Environment конфигурация

```bash
# .env файл
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=localhost,yourdomain.com

# Database
DB_NAME=ev_charging_platform
DB_USER=postgres
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0

# DeyeCloud API
DEYE_APP_ID=your-deye-app-id
DEYE_APP_SECRET=your-deye-app-secret
DEYE_EMAIL=your-deye-email
DEYE_PASSWORD=your-deye-password
DEYE_DATACENTER=eu1
DEYE_COMPANY_ID=your-company-id

# Payment Gateway
STRIPE_SECRET_KEY=sk_test_your-stripe-key
STRIPE_PUBLISHABLE_KEY=pk_test_your-stripe-key
```

---

## API документация

### Authentication

```http
POST /api/auth/login/
Content-Type: application/json

{
    "username": "user@example.com",
    "password": "password123"
}

Response:
{
    "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "user": {
        "id": 1,
        "username": "user@example.com",
        "is_staff": false
    }
}
```

### Station Management API

#### Списък със станции
```http
GET /api/stations/
Authorization: Token your-token-here

Response:
{
    "count": 10,
    "results": [
        {
            "id": 1,
            "name": "Station 1",
            "location": "Sofia, Bulgaria",
            "status": "Available",
            "connectors": [
                {
                    "id": 1,
                    "type": "Type 2",
                    "power": 22,
                    "status": "Available"
                }
            ]
        }
    ]
}
```

#### Стартиране на зарядна сесия
```http
POST /api/stations/{station_id}/start/
Authorization: Token your-token-here

{
    "connector_id": 1,
    "rfid_tag": "1234567890"
}

Response:
{
    "transaction_id": "TXN123456",
    "status": "Started",
    "connector_id": 1,
    "start_time": "2026-01-14T16:00:00Z"
}
```

### Energy Management API

#### Dashboard данни
```http
GET /api/energy/dashboard/api/
Authorization: Token your-token-here

Response:
{
    "current": {
        "total_generation_watts": 6000,
        "average_battery_soc": 75.5,
        "active_inverters": 2,
        "timestamp": "2026-01-14T16:00:00Z",
        "readings": [
            {
                "device_sn": "2409109016",
                "generation_power": 3000,
                "battery_soc": 75.5,
                "connect_status": 1,
                "timestamp": "2026-01-14T16:00:00Z"
            }
        ]
    },
    "daily_stats": {
        "total_energy_kwh": 45.2,
        "peak_generation_watts": 8500,
        "average_battery_soc": 72.3
    }
}
```

#### EV Charging препоръки
```http
POST /api/energy/charging/recommendation/
Authorization: Token your-token-here

{
    "vehicle_id": "EV123",
    "target_soc": 80,
    "current_soc": 30,
    "max_power": 7200
}

Response:
{
    "should_charge": true,
    "available_solar_watts": 6000,
    "charging_power_watts": 6000,
    "estimated_time_hours": 2.5,
    "battery_soc": 75.5
}
```

---

## OCPP интеграция

### OCPP 1.6 протокол

#### Message структура
```json
{
    "MessageTypeId": 2,
    "UniqueId": "123456",
    "Action": "BootNotification",
    "Payload": {
        "chargePointVendor": "VendorX",
        "chargePointModel": "ModelY",
        "chargePointSerialNumber": "SN123456"
    }
}
```

#### WebSocket връзка
```javascript
// OCPP WebSocket връзка
const ws = new WebSocket('ws://localhost:8000/ocpp/station123/');

ws.onopen = function() {
    // Boot notification
    ws.send(JSON.stringify({
        "MessageTypeId": 2,
        "UniqueId": "1",
        "Action": "BootNotification",
        "Payload": {
            "chargePointVendor": "VendorX",
            "chargePointModel": "ModelY"
        }
    }));
};

ws.onmessage = function(event) {
    const message = JSON.parse(event.data);
    console.log('OCPP Message:', message);
};
```

### OCPP съобщения

#### BootNotification
```python
@on(Action.BootNotification)
async def handle_boot_notification(charge_point, payload):
    """Обработка на BootNotification"""
    station = await Station.objects.get_or_create(
        charge_point_id=charge_point.id,
        defaults={
            'vendor': payload.charge_point_vendor,
            'model': payload.charge_point_model,
            'serial_number': payload.charge_point_serial_number
        }
    )
    
    return call_result.BootNotification(
        current_time=datetime.utcnow().isoformat() + 'Z',
        interval=300,
        status=RegistrationStatus.accepted
    )
```

#### StartTransaction
```python
@on(Action.StartTransaction)
async def handle_start_transaction(charge_point, payload):
    """Обработка на StartTransaction"""
    # Валидация на RFID tag
    user = await UserRFID.objects.filter(
        tag=payload.id_tag,
        is_active=True
    ).first()
    
    if user:
        # Създаване на транзакция
        transaction = await Transaction.objects.create(
            transaction_id=generate_transaction_id(),
            charge_point_id=charge_point.id,
            connector_id=payload.connector_id,
            user=user.user,
            start_time=parse_timestamp(payload.timestamp),
            meter_start=payload.meter_start,
            status='Active'
        )
        
        return call_result.StartTransaction(
            transaction_id=transaction.transaction_id,
            id_tag_info={
                "status": AuthorizationStatus.accepted
            }
        )
    else:
        return call_result.StartTransaction(
            id_tag_info={
                "status": AuthorizationStatus.invalid
            }
        )
```

---

## Energy Management

### DeyeCloud интеграция

#### Аутентикация
```python
class DeyeCloudClient:
    async def authenticate(self):
        """OAuth2 базирана аутентикация"""
        auth_payload = {
            "appId": os.getenv('DEYE_APP_ID'),
            "appSecret": os.getenv('DEYE_APP_SECRET'),
            "email": os.getenv('DEYE_EMAIL'),
            "password": self._hash_password(os.getenv('DEYE_PASSWORD')),
            "datacenter": os.getenv('DEYE_DATACENTER'),
            "companyId": os.getenv('DEYE_COMPANY_ID')
        }
        
        response = await self.session.post(
            f"{self.BASE_URL}/api/v1/auth/login",
            json=auth_payload
        )
        
        if response.status_code == 200:
            auth_data = response.json()
            self.token = auth_data['data']['token']
            return True
        else:
            raise DeyeCloudAPIError("Authentication failed")
```

#### Събиране на данни
```python
class InverterDataService:
    async def collect_current_data(self):
        """Събиране на реални данни от инвертори"""
        try:
            # 1. Аутентикация
            await self.deye_client.authenticate()
            
            # 2. Извличане на станции
            stations = await self.deye_client.get_stations_with_devices()
            
            # 3. Събиране на device SNs
            inverter_sns = [
                device['device_sn'] 
                for station in stations 
                for device in station['devices']
            ]
            
            # 4. Извличане на индивидуални данни
            device_data = await self.deye_client.get_device_latest(inverter_sns)
            
            # 5. Извличане на станционни данни
            station_data = await self.deye_client.get_station_latest(self.station_id)
            
            # 6. Обработка и съхранение
            await self.process_and_store_data(device_data, station_data)
            
        except Exception as e:
            logger.error(f"Data collection failed: {e}")
            raise
```

### Smart Charging оптимизация

#### EV Charging алгоритъм
```python
class EVChargingOptimizer:
    def get_charging_recommendation(self, vehicle_id, target_soc, current_soc, max_power):
        """Препоръка за оптимално зареждане"""
        # 1. Взимане на текущи данни
        current_data = self.inverter_service.get_current_generation_summary()
        
        # 2. Изчисляване на налична мощност
        available_solar = current_data['total_generation_watts']
        battery_soc = current_data['average_battery_soc']
        
        # 3. Алгоритъм за оптимизация
        if available_solar >= max_power and battery_soc > 20:
            # Пълна мощност от слънце
            charging_power = max_power
            should_charge = True
        elif available_solar > 1000 and battery_soc > 30:
            # Частично зареждане от слънце
            charging_power = min(available_solar, max_power)
            should_charge = True
        else:
            # Недостатъчно слънце
            charging_power = 0
            should_charge = False
        
        # 4. Изчисляване на време
        if should_charge:
            energy_needed = (target_soc - current_soc) * 50  # kWh
            estimated_time = energy_needed / (charging_power / 1000)
        else:
            estimated_time = 0
        
        return {
            'should_charge': should_charge,
            'available_solar_watts': available_solar,
            'charging_power_watts': charging_power,
            'estimated_time_hours': estimated_time,
            'battery_soc': battery_soc
        }
```

---

## База данни

### Database схема

#### Core таблици
```sql
-- Станции
CREATE TABLE stations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    charge_point_id VARCHAR(100) UNIQUE,
    location VARCHAR(255),
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    status VARCHAR(50) DEFAULT 'Available',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Конектори
CREATE TABLE connectors (
    id SERIAL PRIMARY KEY,
    station_id INTEGER REFERENCES stations(id),
    connector_id INTEGER NOT NULL,
    type VARCHAR(50), -- Type 2, CCS, CHAdeMO
    power DECIMAL(8, 2), -- kW
    status VARCHAR(50) DEFAULT 'Available',
    UNIQUE(station_id, connector_id)
);

-- Транзакции
CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(100) UNIQUE,
    station_id INTEGER REFERENCES stations(id),
    connector_id INTEGER,
    user_id INTEGER REFERENCES auth_user(id),
    start_time TIMESTAMP,
    end_time TIMESTAMP NULL,
    meter_start DECIMAL(12, 4),
    meter_stop DECIMAL(12, 4) NULL,
    status VARCHAR(50) DEFAULT 'Active',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Инвертори
CREATE TABLE inverters (
    id SERIAL PRIMARY KEY,
    device_sn VARCHAR(100) UNIQUE,
    device_id VARCHAR(100),
    station_id INTEGER,
    device_type VARCHAR(50) DEFAULT 'INVERTER',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Измервания от инвертори
CREATE TABLE inverter_readings (
    id SERIAL PRIMARY KEY,
    inverter_id INTEGER REFERENCES inverters(id),
    generation_power DECIMAL(10, 2), -- W
    battery_soc DECIMAL(5, 2), -- %
    grid_power DECIMAL(10, 2), -- W
    station_data JSONB, -- Full station data
    connect_status INTEGER DEFAULT 1,
    timestamp TIMESTAMP DEFAULT NOW()
);
```

#### Billing таблици
```sql
-- Ценови планове
CREATE TABLE pricing_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price_per_kwh DECIMAL(8, 4), -- BGN/kWh
    connection_fee DECIMAL(8, 2),
    monthly_fee DECIMAL(8, 2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Зарядни сесии (billing)
CREATE TABLE charging_sessions (
    id SERIAL PRIMARY KEY,
    transaction_id INTEGER REFERENCES transactions(id),
    user_id INTEGER REFERENCES auth_user(id),
    pricing_plan_id INTEGER REFERENCES pricing_plans(id),
    energy_delivered DECIMAL(10, 4), -- kWh
    duration_minutes INTEGER,
    total_cost DECIMAL(10, 2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Фактури
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(100) UNIQUE,
    user_id INTEGER REFERENCES auth_user(id),
    issue_date DATE,
    due_date DATE,
    subtotal DECIMAL(10, 2),
    tax_rate DECIMAL(5, 2),
    tax_amount DECIMAL(10, 2),
    total DECIMAL(10, 2),
    status VARCHAR(20) DEFAULT 'draft',
    paid_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Database оптимизация

#### Indexes
```sql
-- Performance indexes
CREATE INDEX idx_stations_charge_point_id ON stations(charge_point_id);
CREATE INDEX idx_transactions_station_id ON transactions(station_id);
CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_start_time ON transactions(start_time);
CREATE INDEX idx_inverter_readings_timestamp ON inverter_readings(timestamp);
CREATE INDEX idx_inverter_readings_inverter_id ON inverter_readings(inverter_id);

-- Composite indexes
CREATE INDEX idx_transactions_station_status ON transactions(station_id, status);
CREATE INDEX idx_inverter_readings_inverter_timestamp ON inverter_readings(inverter_id, timestamp);
```

#### Partitioning
```sql
-- Partition inverter_readings по месеци
CREATE TABLE inverter_readings_y2026m01 PARTITION OF inverter_readings
FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE inverter_readings_y2026m02 PARTITION OF inverter_readings
FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
```

---

## Security

### Authentication и Authorization

#### JWT Authentication
```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

JWT_AUTH = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ALGORITHM': 'HS256',
}
```

#### Role-based access control
```python
class IsStationOwner(BasePermission):
    """Permission за собственици на станции"""
    
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user or request.user.is_staff

class IsAdminUser(BasePermission):
    """Permission за администратори"""
    
    def has_permission(self, request, view):
        return request.user and request.user.is_staff
```

### API Security

#### Rate limiting
```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'charging': '10/minute'  # За charging операции
    }
}
```

#### CORS конфигурация
```python
# settings.py
CORS_ALLOWED_ORIGINS = [
    "https://yourdomain.com",
    "https://app.yourdomain.com",
]

CORS_ALLOW_CREDENTIALS = True
```

### Data Encryption

#### Sensitive данни
```python
from cryptography.fernet import Fernet

class EncryptedField(models.CharField):
    """Encrypted database field"""
    
    def __init__(self, *args, **kwargs):
        self.cipher_suite = Fernet(settings.ENCRYPTION_KEY)
        super().__init__(*args, **kwargs)
    
    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return self.cipher_suite.decrypt(value.encode()).decode()
    
    def get_prep_value(self, value):
        if value is None:
            return value
        return self.cipher_suite.encrypt(value.encode()).decode()
```

---

## Monitoring и logging

### Logging конфигурация

```python
# settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'json': {
            'format': '{"level": "{levelname}", "time": "{asctime}", "module": "{module}", "message": "{message}"}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/ev_charging.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'formatter': 'json',
        },
        'ocpp_file': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/ocpp.log',
            'maxBytes': 10485760,
            'backupCount': 5,
            'formatter': 'json',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
        'apps.charging_stations': {
            'handlers': ['file', 'ocpp_file'],
            'level': 'DEBUG',
            'propagate': True,
        },
        'apps.api.energy': {
            'handlers': ['file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
```

### Performance monitoring

#### Django Debug Toolbar
```python
# settings.py
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1']
```

#### Custom metrics
```python
# monitoring/metrics.py
import time
from django.db import connection
from django.core.cache import cache

class PerformanceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time
        
        # Log performance metrics
        cache.set(f'req_time_{request.path}', duration, 60)
        cache.set(f'db_queries_{request.path}', len(connection.queries), 60)
        
        return response
```

### Health checks

```python
# health_checks.py
from django.http import JsonResponse
from django.db import connection
from django.core.cache import cache
import redis

def health_check(request):
    """Comprehensive health check"""
    checks = {
        'database': self._check_database(),
        'redis': self._check_redis(),
        'ocpp_websockets': self._check_ocpp_websockets(),
        'deye_api': self._check_deye_api(),
    }
    
    status = 'healthy' if all(checks.values()) else 'unhealthy'
    
    return JsonResponse({
        'status': status,
        'checks': checks,
        'timestamp': timezone.now().isoformat()
    })

def _check_database(self):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except:
        return False

def _check_redis(self):
    try:
        redis_client = redis.Redis(host='localhost', port=6379, db=0)
        redis_client.ping()
        return True
    except:
        return False
```

---

## Deployment

### Docker конфигурация

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Start application
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "renew_website.asgi:application"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=False
      - DB_HOST=db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - static_volume:/app/static
      - media_volume:/app/media

  db:
    image: postgres:14
    environment:
      - POSTGRES_DB=ev_charging_platform
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery:
    build: .
    command: celery -A renew_website worker -l info
    environment:
      - DB_HOST=db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  celery-beat:
    build: .
    command: celery -A renew_website beat -l info
    environment:
      - DB_HOST=db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

volumes:
  postgres_data:
  static_volume:
  media_volume:
```

### Production конфигурация

```python
# settings/production.py
from .base import *

DEBUG = False
ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com']

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT'),
        'OPTIONS': {
            'sslmode': 'require',
        }
    }
}

# Security
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# Session
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Static files
STATIC_ROOT = '/var/www/static/'
MEDIA_ROOT = '/var/www/media/'

# Logging
LOGGING['handlers']['file']['filename'] = '/var/log/ev_charging/app.log'
LOGGING['handlers']['ocpp_file']['filename'] = '/var/log/ev_charging/ocpp.log'
```

### Nginx конфигурация

```nginx
# /etc/nginx/sites-available/ev_charging
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /path/to/ssl/cert.pem;
    ssl_certificate_key /path/to/ssl/private.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;

    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /var/www/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /var/www/media/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### Backup стратегия

```bash
#!/bin/bash
# backup.sh

# Database backup
pg_dump -h localhost -U postgres ev_charging_platform | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Media files backup
tar -czf media_backup_$(date +%Y%m%d_%H%M%S).tar.gz /var/www/media/

# Upload to S3
aws s3 cp backup_$(date +%Y%m%d_%H%M%S).sql.gz s3://your-backup-bucket/database/
aws s3 cp media_backup_$(date +%Y%m%d_%H%M%S).tar.gz s3://your-backup-bucket/media/

# Clean old backups (keep last 30 days)
find /backup -name "*.sql.gz" -mtime +30 -delete
find /backup -name "*.tar.gz" -mtime +30 -delete
```

---

## Заключение

Тази документация предоставя пълен преглед на EV Charging Platform, включително архитектура, инсталация, API документация, security, monitoring и deployment. Платформата е проектирана да бъде скалируема, сигурна и лесна за поддръжка, като същевременно предоставя всички необходими функционалности за управление на мрежа от зарядни станции с интеграция с възобновяема енергия.