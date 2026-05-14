"""
Tests for charging_stations models.
"""
import pytest
from django.utils import timezone
from django.db import IntegrityError
from renew_website.apps.charging_stations.models import (
    Station, Connector, Transaction, MeterValue, UserRFID, Vehicle
)
from renew_website.apps.charging_stations.tasks import process_meter_values


class TestStationModel:
    """Tests for the Station model."""
    
    def test_create_station(self, db):
        """Test creating a station."""
        station = Station.objects.create(
            address='123 Test Street',
            latitude=42.6977,
            longitude=23.3219,
            connector_type='Type2',
            power_output=22,
            email='test@example.com'
        )
        assert station.id is not None
        assert station.status == 'inactive'  # Default status
        assert station.power_output == 22
    
    def test_station_str(self, station):
        """Test station string representation."""
        result = str(station)
        assert 'Station' in result or 'Test' in result
    
    def test_station_short_address(self, db):
        """Test short_address method."""
        station = Station.objects.create(
            address='A' * 50,  # Long address
            latitude=42.6977,
            longitude=23.3219,
            connector_type='Type2',
            power_output=22,
            email='test@example.com'
        )
        short = station.short_address()
        assert len(short) <= 33  # 30 chars + '...'
        assert short.endswith('...')
    
    def test_station_status_choices(self, station):
        """Test station status choices."""
        valid_statuses = ['active', 'inactive', 'maintenance']
        for status in valid_statuses:
            station.status = status
            station.save()
            station.refresh_from_db()
            assert station.status == status

    def test_station_is_online_false_when_recent_but_inactive(self, station):
        """Inactive stations should render offline immediately after disconnect."""
        station.status = 'inactive'
        station.last_seen = timezone.now()
        station.save(update_fields=['status', 'last_seen'])

        assert station.is_online is False


class TestConnectorModel:
    """Tests for the Connector model."""
    
    def test_create_connector(self, station):
        """Test creating a connector."""
        connector = Connector.objects.create(
            station=station,
            connector_id=1,
            status='available'
        )
        assert connector.id is not None
        assert connector.station == station
    
    def test_connector_unique_together(self, station):
        """Test that station + connector_id must be unique."""
        Connector.objects.create(station=station, connector_id=1)
        with pytest.raises(IntegrityError):
            Connector.objects.create(station=station, connector_id=1)
    
    def test_connector_status_choices(self, connector):
        """Test connector status choices."""
        valid_statuses = [
            'available', 'preparing', 'charging', 'suspendedEV',
            'suspendedEVSE', 'finishing', 'reserved', 'faulted', 'offline'
        ]
        for status in valid_statuses:
            connector.status = status
            connector.save()
            connector.refresh_from_db()
            assert connector.status == status
    
    def test_connector_str(self, connector):
        """Test connector string representation."""
        result = str(connector)
        assert 'Connector' in result


class TestTransactionModel:
    """Tests for the Transaction model."""
    
    def test_create_transaction(self, connector, user_rfid):
        """Test creating a transaction."""
        transaction = Transaction.objects.create(
            connector=connector,
            id_tag=user_rfid.tag,
            meter_start=0
        )
        assert transaction.id is not None
        assert transaction.status == 'active'
        assert transaction.started_at is not None
    
    def test_transaction_complete(self, transaction):
        """Test completing a transaction."""
        transaction.status = 'completed'
        transaction.meter_stop = 5000  # 5 kWh
        transaction.stopped_at = timezone.now()
        transaction.save()
        
        transaction.refresh_from_db()
        assert transaction.status == 'completed'
        assert transaction.meter_stop == 5000
    
    def test_transaction_energy_calculation(self, transaction):
        """Test energy calculation from meter values."""
        transaction.meter_start = 1000
        transaction.meter_stop = 6000  # 5000 Wh = 5 kWh
        transaction.save()
        
        energy_wh = transaction.meter_stop - transaction.meter_start
        assert energy_wh == 5000
    
    def test_transaction_ordering(self, connector, user_rfid):
        """Test that transactions are ordered newest first."""
        t1 = Transaction.objects.create(
            connector=connector, id_tag=user_rfid.tag, meter_start=0
        )
        t2 = Transaction.objects.create(
            connector=connector, id_tag=user_rfid.tag, meter_start=100
        )
        
        transactions = list(Transaction.objects.all())
        assert transactions[0] == t2  # Newest first
        assert transactions[1] == t1


class TestVehicleModel:
    def test_create_vehicle_profile(self, db):
        vehicle = Vehicle.objects.create(
            vehicle_identifier='veh-001',
            vin='VIN00000000000001',
            registration_number='CB1234AB',
            manufacturer='Hyundai',
            model_name='IONIQ 5',
            model_year=2024,
            trim='Long Range',
            color='Silver',
            battery_capacity_kwh=77.4,
            last_known_soc_percent=48.5,
        )

        assert vehicle.id is not None
        assert vehicle.model_year == 2024
        assert vehicle.trim == 'Long Range'
        assert vehicle.last_known_soc_percent == 48.5

    def test_process_meter_values_updates_vehicle_latest_soc(self, transaction):
        vehicle = Vehicle.objects.create(vehicle_identifier=transaction.id_tag)
        transaction.vehicle = vehicle
        transaction.save(update_fields=['vehicle'])

        process_meter_values(
            station_id=transaction.connector.station_id,
            connector_id=transaction.connector_id,
            transaction_id=transaction.id,
            power_w=7400,
            energy_wh=1200,
            soc_percentage=56.0,
            mv_data={'source': 'test'},
        )

        vehicle.refresh_from_db()
        assert vehicle.last_known_soc_percent == 56.0


class TestMeterValueModel:
    """Tests for the MeterValue model."""
    
    def test_create_meter_value(self, transaction):
        """Test creating a meter value."""
        mv = MeterValue.objects.create(
            transaction=transaction,
            value=1000,
            data={'samples': []}
        )
        assert mv.id is not None
        assert mv.timestamp is not None
    
    def test_meter_value_json_data(self, transaction):
        """Test storing JSON data in meter value."""
        data = {
            'start': {'meter_start': 0, 'timestamp': '2024-01-01T00:00:00Z'},
            'samples': [
                {'power': 7400, 'timestamp': '2024-01-01T00:01:00Z'},
                {'power': 7600, 'timestamp': '2024-01-01T00:02:00Z'},
            ]
        }
        mv = MeterValue.objects.create(
            transaction=transaction,
            value=1000,
            data=data
        )
        
        mv.refresh_from_db()
        assert mv.data['samples'][0]['power'] == 7400


class TestUserRFIDModel:
    """Tests for the UserRFID model."""
    
    def test_create_rfid(self, db):
        """Test creating an RFID tag."""
        rfid = UserRFID.objects.create(
            tag='ABC123',
            owner_name='John Doe'
        )
        assert rfid.id is not None
        assert rfid.is_active is True  # Default
    
    def test_rfid_unique_tag(self, db):
        """Test that RFID tags must be unique."""
        UserRFID.objects.create(tag='UNIQUE123')
        with pytest.raises(IntegrityError):
            UserRFID.objects.create(tag='UNIQUE123')
    
    def test_rfid_station_association(self, user_rfid, station):
        """Test RFID to station many-to-many relationship."""
        assert station in user_rfid.stations.all()
    
    def test_rfid_multiple_stations(self, user_rfid, db):
        """Test RFID can access multiple stations."""
        station2 = Station.objects.create(
            address='Second Station',
            latitude=42.0,
            longitude=23.0,
            connector_type='CCS',
            power_output=50,
            email='station2@example.com'
        )
        user_rfid.stations.add(station2)
        
        assert user_rfid.stations.count() == 2
    
    def test_rfid_str(self, user_rfid):
        """Test RFID string representation."""
        result = str(user_rfid)
        assert user_rfid.owner_name in result or user_rfid.tag in result
    
    def test_rfid_deactivate(self, user_rfid):
        """Test deactivating an RFID tag."""
        user_rfid.is_active = False
        user_rfid.save()
        
        user_rfid.refresh_from_db()
        assert user_rfid.is_active is False
