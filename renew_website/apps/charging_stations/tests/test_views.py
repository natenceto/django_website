"""
Tests for charging_stations views.
"""
import pytest
from django.urls import reverse
from renew_website.apps.charging_stations.models import Station, Connector


class TestStationsView:
    """Tests for the stations view."""
    
    def test_stations_requires_login(self, client):
        """Test that stations view requires authentication."""
        response = client.get('/charging_stations/stations/')
        assert response.status_code == 302  # Redirect to login
    
    def test_stations_requires_admin(self, authenticated_client):
        """Test that stations view requires admin/staff status."""
        response = authenticated_client.get('/charging_stations/stations/')
        assert response.status_code == 302  # Redirect (not staff)
    
    def test_stations_admin_access(self, admin_client, station):
        """Test admin can access stations view."""
        response = admin_client.get('/charging_stations/stations/')
        assert response.status_code == 200
    
    def test_stations_list_display(self, admin_client, station, connector):
        """Test stations are displayed in the list."""
        response = admin_client.get('/charging_stations/stations/')
        assert response.status_code == 200
        content = response.content.decode()
        assert station.address in content or 'Test' in content


class TestStatisticsView:
    """Tests for the statistics view."""
    
    def test_statistics_requires_login(self, client):
        """Test that statistics view requires authentication."""
        response = client.get('/charging_stations/statistics/')
        assert response.status_code == 302
    
    def test_statistics_admin_access(self, admin_client):
        """Test admin can access statistics view."""
        response = admin_client.get('/charging_stations/statistics/')
        assert response.status_code == 200


class TestStationActions:
    """Tests for station action endpoints (start/stop charging)."""
    
    @pytest.fixture
    def station_with_connector(self, station):
        """Create a station with a connector."""
        Connector.objects.create(
            station=station,
            connector_id=1,
            status='available'
        )
        return station
    
    def test_start_no_station_selected(self, admin_client):
        """Test start action with no station selected."""
        response = admin_client.post(
            '/charging_stations/stations/',
            {'action': 'start'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'No station' in data['message']
    
    def test_start_station_not_connected(self, admin_client, station):
        """Test start action when station is not connected."""
        response = admin_client.post(
            '/charging_stations/stations/',
            {
                'action': 'start',
                'station_ids': [station.id]
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        assert response.status_code == 200
        data = response.json()
        # Station not in ACTIVE_STATIONS, should fail
        assert 'Not connected' in str(data.get('results', data.get('message', '')))
