# Architecture Analysis: Database Migration & Energy Management

## 1. Overview
This document analyzes the transition from a monolithic SQLite database to a hybrid architecture:
- **SQLite**: User Management, Authentication, Permissions (Roles).
- **PostgreSQL**: Charging Stations, Inverters, Weather Data, Energy Management.
- **Microservices Support**: Integration of Celery (Task Queue) and Redis (Broker/Cache) for background processing.

## 2. Redundancy & Model Optimization (Cleanup)

### 2.1. Charging Sessions vs Transactions
- **Current State**: 
  - `Transaction` (OCPP data, meter values, technical logs).
  - `ChargingSession` (Billing, User association, Pricing).
- **Analysis**: Ideally, these should be 1:1, but `Transaction` is strictly technical (OCPP), while `ChargingSession` handles business logic.
- **Recommendation**: Maintain separation but ensure strict linkage. 
  - **Issue**: `Transaction` linking to `Connector` (Postgres) is fine.
  - **Issue**: `ChargingSession` linking to `User` (SQLite) is **CRITICAL**. Cross-Database Foreign Keys are not supported by Django.

### 2.2. User Association (The Cross-DB Challenge)
Models in `charging_stations` that reference `auth.User`:
- `ChargingSession.user`
- `PaymentMethod.user`
- `Invoice.user`
- `UserRFID.user`
- `Station.owner` (implied by `email` field? No, currently email string).

**Problem**: If `auth.User` remains in SQLite and these models move to PostgreSQL, `models.ForeignKey` will fail during migration and runtime integrity checks.

**Solution**:
1. **Refactor ForeignKeys to IntegerFields**:
   - Change `user = ForeignKey(User)` to `user_id = IntegerField(db_index=True)`.
   - Implement a **Service Layer** (`UserService`) to fetch User objects by ID from the `default` (SQLite) database when needed.
   - **Pros**: complete decoupling. **Cons**: No database-level integrity (ON DELETE CASCADE must be handled manually via signals).

### 2.3. Station & Inverter Link
- `Inverter` model uses `station_id = IntegerField()`. This is already decoupled and ready for the split if `Station` is in Postgres. 
- *Correction*: If both `Inverter` and `Station` are in PostgreSQL, this *should* be a true `ForeignKey` to leverage ORM capabilities (select_related).
- **Recommendation**: Convert `Inverter.station_id` to `ForeignKey(Station)` since both will reside in the same PostgreSQL database.

## 3. Missing Components & Additions

### 3.1. Background Processing (Celery + Redis)
- **Current**: Data collection is triggered via HTTP requests (`views.py` or frontend polling).
- **Requirement**: Energy redistribution requires complex periodic algorithms.
- **Addition**:
  - `celery.py` configuration.
  - Redis container in `docker-compose.yml`.
  - Periodic Tasks (Celery Beat) for:
    - 3-min Inverter Polling.
    - 15-min Weather Fetch.
    - Real-time "Smart Charging" adjustment signals.

### 3.2. Database Routing
- **Requirement**: A Django Database Router is needed to direct traffic.
  - `auth`, `admin`, `contenttypes`, `sessions`, `accounts` -> `default` (SQLite).
  - `charging_stations`, `energy`, `weather` -> `postgres_db`.

### 3.3. CRUD Operations
- **Requirement**: "Access to CRUD operations for everything".
- **Action**: Ensure all Postgres models are registered in `admin.py`.
- **Note**: Admin panel might struggle with Cross-DB relations (e.g., filtering Sessions by User Username). Custom Admin classes will be needed to look up Users manually.

## 4. Implementation Plan (Branch: `database`)

1. **Infrastructure**:
   - Add PostgreSQL and Redis to `docker-compose.yml`.
   - Install `psycopg2-binary`, `celery`, `redis` (already in requirements?).

2. **Configuration**:
   - Update `settings.py` (DATABASES, CELERY_BROKER_URL).
   - Create `renew_website/routers.py`.

3. **Code Refactoring**:
   - **Step 3.1**: Decouple User relations in `charging_stations` and `accounts`. Replace `ForeignKey(User)` with `user_id`.
   - **Step 3.2**: Strengthen `Inverter` -> `Station` relation (foreign key).

4. **Migration**:
   - Create migrations for the schema changes (FK to Int).
   - Apply migrations to the new PostgreSQL DB.

5. **UI/Logic Updates**:
   - Update Views/Services to fetch User data separately when displaying Charging Sessions.
