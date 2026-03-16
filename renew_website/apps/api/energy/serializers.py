"""
Energy management API serializers.
"""
from rest_framework import serializers
from .models import Inverter, InverterReading, WorkMode


class WorkModeSerializer(serializers.ModelSerializer):
    """Serializer for WorkMode model."""
    
    class Meta:
        model = WorkMode
        fields = [
            'mode', 'control_mode', 'is_active', 
            'algorithm_selected_mode', 'last_updated'
        ]


class InverterSerializer(serializers.ModelSerializer):
    """Serializer for Inverter model."""
    
    class Meta:
        model = Inverter
        fields = [
            'id', 'device_sn', 'device_id', 'device_type', 
            'product_id', 'station_id', 'is_active', 'created_at'
        ]


class InverterReadingSerializer(serializers.ModelSerializer):
    """Serializer for InverterReading model."""
    inverter = InverterSerializer(read_only=True)
    
    class Meta:
        model = InverterReading
        fields = [
            'id', 'inverter', 'generation_power', 'battery_soc',
            'grid_power', 'connect_status', 'timestamp', 'collection_time'
        ]




class DashboardDataSerializer(serializers.Serializer):
    """Serializer for dashboard data response."""
    total_generation_watts = serializers.FloatField()
    average_battery_soc = serializers.FloatField()
    active_inverters = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    readings = InverterReadingSerializer(many=True)
    
    # Daily stats
    total_energy_kwh = serializers.FloatField()
    peak_generation_watts = serializers.FloatField()


class ChargingRecommendationRequestSerializer(serializers.Serializer):
    """Serializer for charging recommendation request."""
    vehicle_id = serializers.CharField(max_length=100)
    target_soc = serializers.IntegerField(min_value=0, max_value=100)
    current_soc = serializers.IntegerField(min_value=0, max_value=100)
    max_power = serializers.IntegerField(min_value=0)


class ChargingRecommendationResponseSerializer(serializers.Serializer):
    """Serializer for charging recommendation response."""
    should_charge = serializers.BooleanField()
    available_solar_watts = serializers.FloatField()
    charging_power_watts = serializers.FloatField()
    estimated_time_hours = serializers.FloatField()
    battery_soc = serializers.FloatField()
