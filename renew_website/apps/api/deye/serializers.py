"""
DeyeCloud API serializers.
"""
from rest_framework import serializers


class DeviceSerializer(serializers.Serializer):
    """Serializer for device data from DeyeCloud API."""
    device_sn = serializers.CharField()
    device_id = serializers.CharField()
    device_type = serializers.CharField()
    product_id = serializers.CharField()
    connect_status = serializers.IntegerField()
    is_master = serializers.BooleanField(default=False)


class StationSerializer(serializers.Serializer):
    """Serializer for station data from DeyeCloud API."""
    station_id = serializers.IntegerField()
    station_name = serializers.CharField()
    capacity = serializers.FloatField()
    devices = DeviceSerializer(many=True)


class DeviceLatestSerializer(serializers.Serializer):
    """Serializer for device latest data response."""
    device_sn = serializers.CharField()
    generation_power = serializers.FloatField()
    battery_soc = serializers.FloatField()
    grid_power = serializers.FloatField()
    daily_energy = serializers.FloatField()
    total_energy = serializers.FloatField()
    timestamp = serializers.IntegerField()
    status = serializers.IntegerField()
    temperature = serializers.FloatField()
    voltage = serializers.FloatField()
    current = serializers.FloatField()


class StationLatestSerializer(serializers.Serializer):
    """Serializer for station latest data response."""
    station_id = serializers.IntegerField()
    generation_power = serializers.FloatField()
    battery_soc = serializers.FloatField()
    grid_power = serializers.FloatField()
    daily_energy = serializers.FloatField()
    monthly_energy = serializers.FloatField()
    total_energy = serializers.FloatField()
    capacity = serializers.FloatField()
    efficiency = serializers.FloatField()
    timestamp = serializers.IntegerField()


class StationListSerializer(serializers.Serializer):
    """Serializer for station list response."""
    stations = StationSerializer(many=True)


class DeviceListSerializer(serializers.Serializer):
    """Serializer for device list response."""
    devices = DeviceSerializer(many=True)
