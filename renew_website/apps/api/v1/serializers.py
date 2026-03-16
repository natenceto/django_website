"""
API Serializers for EV Charging Platform.
"""
from rest_framework import serializers
from renew_website.apps.charging_stations.models import (
    Station, Connector, Transaction, MeterValue, UserRFID
)


class ConnectorSerializer(serializers.ModelSerializer):
    """Serializer for Connector model."""
    
    class Meta:
        model = Connector
        fields = [
            'id', 'connector_id', 'status', 'availability',
            'vendor_connector_id', 'last_updated'
        ]
        read_only_fields = ['id', 'last_updated']


class StationListSerializer(serializers.ModelSerializer):
    """Serializer for Station list view (minimal fields)."""
    connector_count = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()
    
    class Meta:
        model = Station
        fields = [
            'id', 'address', 'latitude', 'longitude', 'model',
            'connector_type', 'power_output', 'status', 'is_online',
            'connector_count'
        ]
    
    def get_connector_count(self, obj):
        return obj.connectors.count()
    
    def get_is_online(self, obj):
        try:
            from renew_website.apps.charging_stations.registry import is_station_active
        except ImportError:
            # Fallback if the module does not exist
            def is_station_active(station_id):
                return False
        return is_station_active(obj.id)


class StationDetailSerializer(serializers.ModelSerializer):
    """Serializer for Station detail view (full fields)."""
    connectors = ConnectorSerializer(many=True, read_only=True)
    is_online = serializers.SerializerMethodField()
    
    class Meta:
        model = Station
        fields = [
            'id', 'address', 'latitude', 'longitude', 'model',
            'connector_type', 'power_output', 'status', 'email',
            'last_seen', 'is_online', 'connectors'
        ]
        read_only_fields = ['id', 'last_seen']
    
    def get_is_online(self, obj):
        from renew_website.apps.charging_stations.registry import is_station_active
        return is_station_active(obj.id)


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for Transaction model."""
    station_id = serializers.IntegerField(source='connector.station.id', read_only=True)
    station_address = serializers.CharField(source='connector.station.address', read_only=True)
    connector_number = serializers.IntegerField(source='connector.connector_id', read_only=True)
    energy_kwh = serializers.SerializerMethodField()
    duration_minutes = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'station_id', 'station_address', 'connector_number',
            'id_tag', 'started_at', 'stopped_at', 'meter_start', 'meter_stop',
            'requested_power_kw', 'status', 'energy_kwh', 'duration_minutes'
        ]
        read_only_fields = ['id', 'started_at']
    
    def get_energy_kwh(self, obj):
        if obj.meter_stop and obj.meter_start:
            return round((obj.meter_stop - obj.meter_start) / 1000, 2)
        return None
    
    def get_duration_minutes(self, obj):
        if obj.stopped_at and obj.started_at:
            delta = obj.stopped_at - obj.started_at
            return int(delta.total_seconds() / 60)
        return None


class MeterValueSerializer(serializers.ModelSerializer):
    """Serializer for MeterValue model."""
    
    class Meta:
        model = MeterValue
        fields = ['id', 'transaction', 'timestamp', 'value', 'data']
        read_only_fields = ['id', 'timestamp']


class UserRFIDSerializer(serializers.ModelSerializer):
    """Serializer for UserRFID model."""
    station_ids = serializers.PrimaryKeyRelatedField(
        source='stations',
        many=True,
        queryset=Station.objects.all(),
        required=False
    )
    
    class Meta:
        model = UserRFID
        fields = [
            'id', 'tag', 'owner_name', 'is_active', 'station_ids',
            'created_at', 'last_updated', 'notes'
        ]
        read_only_fields = ['id', 'created_at', 'last_updated']


class ChargingSessionStartSerializer(serializers.Serializer):
    """Serializer for starting a charging session."""
    station_id = serializers.IntegerField()
    connector_id = serializers.IntegerField(default=1)
    rfid_tag = serializers.CharField(max_length=50, required=False)
    power_kw = serializers.IntegerField(required=False, min_value=1, max_value=350)


class ChargingSessionStopSerializer(serializers.Serializer):
    """Serializer for stopping a charging session."""
    transaction_id = serializers.IntegerField()


class StationStatisticsSerializer(serializers.Serializer):
    """Serializer for station statistics."""
    total_stations = serializers.IntegerField()
    online_stations = serializers.IntegerField()
    total_connectors = serializers.IntegerField()
    available_connectors = serializers.IntegerField()
    active_sessions = serializers.IntegerField()
    total_energy_kwh = serializers.FloatField()
    total_sessions_today = serializers.IntegerField()
