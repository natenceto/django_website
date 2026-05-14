"""
Tests for charging_stations views.
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from renew_website.apps.charging_stations.models import Station, Connector, MeterValue, StationStatusHistory


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

    def test_statistics_renders_analytics_sections(self, admin_client, completed_transaction):
        """Test analytics-oriented sections render on the statistics page."""
        station = completed_transaction.connector.station
        start = timezone.now() - timezone.timedelta(hours=2)
        StationStatusHistory.objects.create(station=station, status='active', reason='test-start', observed_at=start)
        StationStatusHistory.objects.create(station=station, status='inactive', reason='test-offline', observed_at=start + timezone.timedelta(hours=1))
        StationStatusHistory.objects.create(station=station, status='active', reason='test-online', observed_at=start + timezone.timedelta(hours=1, minutes=30))

        MeterValue.objects.create(
            transaction=completed_transaction,
            timestamp=timezone.now(),
            energy_wh=5000,
            power_w=7400,
            soc_percentage=48.0,
            data={
                'raw_payload': [
                    {
                        'sampled_value': [
                            {'measurand': 'Current.Import', 'value': '16', 'unit': 'A'},
                            {'measurand': 'Voltage', 'value': '230', 'unit': 'V'},
                        ]
                    }
                ],
                'session_context': {'requested_power_mode': 'manual'},
            },
        )

        response = admin_client.get('/charging_stations/statistics/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Power &amp; Energy Timeline' in content
        assert 'Session Duration Distribution' in content
        assert 'Charger Utilization' in content
        assert 'Meter Values Explorer' in content
        assert 'Offline Time' in content
        assert 'Latest Buckets' in content

    def test_statistics_supports_specific_date_range_selector(self, admin_client):
        selected_date = timezone.localdate().strftime('%Y-%m-%d')

        response = admin_client.get('/charging_stations/statistics/', {'timerange': 'date', 'date': selected_date})

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Specific Date' in content
        assert f'value="{selected_date}"' in content

    def test_statistics_timeline_csv_export(self, admin_client, completed_transaction):
        MeterValue.objects.create(
            transaction=completed_transaction,
            timestamp=timezone.now(),
            energy_wh=5000,
            power_w=7400,
            data={'raw_payload': [], 'session_context': {}},
        )

        response = admin_client.get('/charging_stations/statistics/export/timeline/', {'timerange': '24h'})

        assert response.status_code == 200
        assert response['Content-Type'] == 'text/csv'
        content = response.content.decode()
        assert 'Bucket Start,Total Charging Power (kW),Delivered Energy Delta (kWh)' in content

    def test_statistics_meter_explorer_uses_ten_rows_per_page(self, admin_client, completed_transaction):
        for offset in range(12):
            MeterValue.objects.create(
                transaction=completed_transaction,
                timestamp=timezone.now() - timedelta(minutes=offset),
                energy_wh=1000 + offset,
                power_w=7000,
                data={'raw_payload': [], 'session_context': {}},
            )

        response = admin_client.get('/charging_stations/statistics/', {'timerange': '24h'})

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Showing 10 rows per page.' in content
        assert 'Page 1 of 2' in content


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
