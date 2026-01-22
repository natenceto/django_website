"""
Tests for RFID authorization logic.
"""
import pytest
from django.utils import timezone
from renew_website.apps.charging_stations.models import Station, Connector, UserRFID


class TestRFIDAuthorization:
    """Tests for RFID authorization logic."""
    
    def test_valid_rfid_for_station(self, user_rfid, station):
        """Test that valid RFID is authorized for its station."""
        is_authorized = UserRFID.objects.filter(
            tag=user_rfid.tag,
            stations__id=station.id,
            is_active=True
        ).exists()
        assert is_authorized is True
    
    def test_invalid_rfid_tag(self, station):
        """Test that invalid RFID tag is not authorized."""
        is_authorized = UserRFID.objects.filter(
            tag='INVALID_TAG_123',
            stations__id=station.id,
            is_active=True
        ).exists()
        assert is_authorized is False
    
    def test_rfid_wrong_station(self, user_rfid, db):
        """Test that RFID is not authorized for wrong station."""
        other_station = Station.objects.create(
            address='Other Station',
            latitude=42.0,
            longitude=23.0,
            connector_type='CCS',
            power_output=50,
            email='other@example.com'
        )
        # user_rfid is NOT associated with other_station
        is_authorized = UserRFID.objects.filter(
            tag=user_rfid.tag,
            stations__id=other_station.id,
            is_active=True
        ).exists()
        assert is_authorized is False
    
    def test_deactivated_rfid(self, user_rfid, station):
        """Test that deactivated RFID is not authorized."""
        user_rfid.is_active = False
        user_rfid.save()
        
        is_authorized = UserRFID.objects.filter(
            tag=user_rfid.tag,
            stations__id=station.id,
            is_active=True
        ).exists()
        assert is_authorized is False
    
    def test_rfid_multiple_stations_authorization(self, user_rfid, station, db):
        """Test RFID authorized for multiple stations."""
        station2 = Station.objects.create(
            address='Station 2',
            latitude=42.1,
            longitude=23.1,
            connector_type='Type2',
            power_output=22,
            email='station2@example.com'
        )
        user_rfid.stations.add(station2)
        
        # Should be authorized for both
        for s in [station, station2]:
            is_authorized = UserRFID.objects.filter(
                tag=user_rfid.tag,
                stations__id=s.id,
                is_active=True
            ).exists()
            assert is_authorized is True


class TestConnectorAvailability:
    """Tests for connector availability checks."""
    
    def test_available_connector(self, connector):
        """Test checking if connector is available."""
        assert connector.status == 'available'
        assert connector.availability == 'operative'
    
    def test_charging_connector_not_available(self, connector):
        """Test that charging connector is not available for new session."""
        connector.status = 'charging'
        connector.save()
        
        available_connectors = Connector.objects.filter(
            station=connector.station,
            status='available',
            availability='operative'
        )
        assert available_connectors.count() == 0
    
    def test_inoperative_connector(self, connector):
        """Test that inoperative connector is not available."""
        connector.availability = 'inoperative'
        connector.save()
        
        available_connectors = Connector.objects.filter(
            station=connector.station,
            status='available',
            availability='operative'
        )
        assert available_connectors.count() == 0
    
    def test_faulted_connector(self, connector):
        """Test that faulted connector is not available."""
        connector.status = 'faulted'
        connector.save()
        
        available_connectors = Connector.objects.filter(
            station=connector.station,
            status='available'
        )
        assert available_connectors.count() == 0
