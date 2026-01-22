"""
Pytest configuration and fixtures for the EV Charging Platform.
"""
import pytest
from django.contrib.auth.models import User
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async


@pytest.fixture
async def websocket_communicator():
    """Create a WebSocket communicator for testing."""
    from renew_website.apps.charging_stations.consumers import ChargePointConsumer
    return WebsocketCommunicator(ChargePointConsumer.as_asgi(), "/ws/charging_stations/1/")


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def admin_user(db):
    """Create an admin user."""
    return User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='adminpass123'
    )


@pytest.fixture
def station(db):
    """Create a test charging station."""
    from renew_website.apps.charging_stations.models import Station
    return Station.objects.create(
        address='Test Address 123',
        latitude=42.6977,
        longitude=23.3219,
        connector_type='Type2',
        power_output=22,
        status='inactive',
        email='station@example.com'
    )


@pytest.fixture
def active_station(db, station):
    """Create an active charging station."""
    station.status = 'active'
    station.save()
    return station


@pytest.fixture
def connector(db, station):
    """Create a test connector."""
    from renew_website.apps.charging_stations.models import Connector
    return Connector.objects.create(
        station=station,
        connector_id=1,
        status='available'
    )


@pytest.fixture
def user_rfid(db, station):
    """Create a test RFID tag."""
    from renew_website.apps.charging_stations.models import UserRFID
    rfid = UserRFID.objects.create(
        tag='TEST123456',
        owner_name='Test User',
        is_active=True
    )
    rfid.stations.add(station)
    return rfid


@pytest.fixture
def transaction(db, connector, user_rfid):
    """Create a test transaction."""
    from renew_website.apps.charging_stations.models import Transaction
    return Transaction.objects.create(
        connector=connector,
        id_tag=user_rfid.tag,
        meter_start=0,
        status='active'
    )


@pytest.fixture
def completed_transaction(db, connector, user_rfid):
    """Create a completed transaction."""
    from renew_website.apps.charging_stations.models import Transaction
    from django.utils import timezone
    return Transaction.objects.create(
        connector=connector,
        id_tag=user_rfid.tag,
        meter_start=0,
        meter_stop=5000,
        status='completed',
        stopped_at=timezone.now()
    )


@pytest.fixture
def authenticated_client(client, user):
    """Return a client logged in as a regular user."""
    client.login(username='testuser', password='testpass123')
    return client


@pytest.fixture
def admin_client(client, admin_user):
    """Return a client logged in as admin."""
    client.login(username='admin', password='adminpass123')
    return client
