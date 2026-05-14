"""
API Serializers for EV Charging Platform.
"""
from typing import Any, Optional

from rest_framework import serializers
from renew_website.apps.charging_stations.models import (
    Station, Connector, Transaction, MeterValue, UserRFID
)

from renew_website.apps.api.schema import extend_schema_field


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
    
    @extend_schema_field(serializers.IntegerField())
    def get_connector_count(self, obj) -> int:
        return obj.connectors.count()
    
    @extend_schema_field(serializers.BooleanField())
    def get_is_online(self, obj) -> bool:
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
    
    @extend_schema_field(serializers.BooleanField())
    def get_is_online(self, obj) -> bool:
        from renew_website.apps.charging_stations.registry import is_station_active
        return is_station_active(obj.id)


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for Transaction model."""
    station_id = serializers.IntegerField(source='connector.station.id', read_only=True)
    station_address = serializers.CharField(source='connector.station.address', read_only=True)
    connector_number = serializers.IntegerField(source='connector.connector_id', read_only=True)
    energy_kwh = serializers.SerializerMethodField()
    duration_minutes = serializers.SerializerMethodField()
    session_context = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = [
            'id', 'station_id', 'station_address', 'connector_number',
            'id_tag', 'started_at', 'stopped_at', 'meter_start', 'meter_stop',
            'requested_power_kw', 'status', 'energy_kwh', 'duration_minutes', 'session_context'
        ]
        read_only_fields = ['id', 'started_at']
    
    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_energy_kwh(self, obj) -> Optional[float]:
        if obj.meter_stop and obj.meter_start:
            return round((obj.meter_stop - obj.meter_start) / 1000, 2)
        return None
    
    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_duration_minutes(self, obj) -> Optional[int]:
        if obj.stopped_at and obj.started_at:
            delta = obj.stopped_at - obj.started_at
            return int(delta.total_seconds() / 60)
        return None

    @extend_schema_field(serializers.JSONField())
    def get_session_context(self, obj) -> dict[str, Any]:
        latest_meter = obj.meter_values.order_by('-timestamp', '-id').first()
        if not latest_meter or not isinstance(latest_meter.data, dict):
            return {}
        return latest_meter.data.get('session_context', {})


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
    vehicle_soc = serializers.FloatField(required=False, min_value=0, max_value=100)
    target_soc = serializers.FloatField(required=False, min_value=1, max_value=100)
    estimated_departure_hours = serializers.FloatField(required=False, min_value=0.1, max_value=168)
    priority_weight = serializers.FloatField(required=False, min_value=0.1, max_value=10)
    battery_capacity_kwh = serializers.FloatField(required=False, min_value=1, max_value=300)
    max_acceptance_kw = serializers.FloatField(required=False, min_value=1, max_value=350)


class ChargingSessionStopSerializer(serializers.Serializer):
    """Serializer for stopping a charging session."""
    transaction_id = serializers.IntegerField()


class ChargingSessionStartResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    station_id = serializers.IntegerField()
    connector_id = serializers.IntegerField()
    rfid_tag = serializers.CharField()
    power_kw = serializers.IntegerField(required=False, allow_null=True)
    command_id = serializers.CharField()
    session_context = serializers.JSONField()


class ChargingSessionStopResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    transaction_id = serializers.IntegerField()
    station_id = serializers.IntegerField()
    command_id = serializers.CharField()


class V1ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()


class StationStatisticsSerializer(serializers.Serializer):
    """Serializer for station statistics."""
    total_stations = serializers.IntegerField()
    online_stations = serializers.IntegerField()
    total_connectors = serializers.IntegerField()
    available_connectors = serializers.IntegerField()
    active_sessions = serializers.IntegerField()
    total_energy_kwh = serializers.FloatField()
    total_sessions_today = serializers.IntegerField()
