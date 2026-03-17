"""
DeyeCloud API serializers.
Refactored to support both Cloud and Local data sources via Manager.
"""
from rest_framework import serializers
from datetime import datetime

class BaseInverterSerializer(serializers.Serializer):
    """
    Common fields for both Cloud and Local data.
    Acts as the contract for the frontend/dashboard.
    """
    device_sn = serializers.CharField()
    timestamp = serializers.DateTimeField(required=False)
    
    # Common core metrics (normalized)
    generation_power = serializers.FloatField(required=False, default=0.0)
    battery_soc = serializers.FloatField(required=False, default=0.0)
    grid_power = serializers.FloatField(required=False, default=0.0) 
    load_power = serializers.FloatField(required=False, default=0.0)
    
    daily_energy = serializers.FloatField(required=False, default=0.0)
    total_energy = serializers.FloatField(required=False, default=0.0)

class DeyeCloudSerializer(BaseInverterSerializer):
    """
    Serializer for Cloud Data.
    Extracts values from the cloud specific response structure.
    """
    # Override fields from Base to provide specific sources
    # Assuming 'data' passes a dict with keys matching cloud response
    
    # We use SerializerMethodField because cloud structure varies wildly (dataList vs flat)
    generation_power = serializers.SerializerMethodField()
    battery_soc = serializers.SerializerMethodField()
    grid_power = serializers.SerializerMethodField()
    load_power = serializers.SerializerMethodField()
    daily_energy = serializers.SerializerMethodField()
    total_energy = serializers.SerializerMethodField()

    def get_generation_power(self, obj):
        # Check standard keys
        if 'generationPower' in obj: return float(obj['generationPower'])
        return self._find_in_datalist(obj, ['TotalSolarPower', 'ActivePower', 'Pac'])

    def get_battery_soc(self, obj):
        if 'batterySOC' in obj: return float(obj['batterySOC'])
        return self._find_in_datalist(obj, ['BatterySOC', 'SOC'])

    def get_grid_power(self, obj):
        if 'gridPower' in obj: return float(obj['gridPower'])
        return self._find_in_datalist(obj, ['GridActivePower', 'TotalGridPower'])
        
    def get_load_power(self, obj):
        # Cloud often doesn't give load power directly, calculated or separate key
        return self._find_in_datalist(obj, ['TotalLoadPower', 'LoadPower'])

    def get_daily_energy(self, obj):
        if 'dailyEnergy' in obj: return float(obj['dailyEnergy'])
        return self._find_in_datalist(obj, ['DailyActiveProduction', 'DailyEnergy'])

    def get_total_energy(self, obj):
        if 'totalEnergy' in obj: return float(obj['totalEnergy'])
        return self._find_in_datalist(obj, ['TotalActiveProduction', 'TotalEnergy'])

    def _find_in_datalist(self, obj, keys):
        # Helper to search in 'dataList' if present
        data_list = obj.get('dataList', [])
        if not data_list: return 0.0
        
        for item in data_list:
            if item.get('key') in keys:
                return float(item.get('value', 0))
        return 0.0

class DeyeLocalSerializer(BaseInverterSerializer):
    """
    Serializer for Local Modbus Data.
    Maps local_client snake_case keys to standard fields.
    """
    generation_power = serializers.SerializerMethodField()
    battery_soc = serializers.SerializerMethodField()
    grid_power = serializers.SerializerMethodField()
    load_power = serializers.SerializerMethodField()
    daily_energy = serializers.SerializerMethodField()
    total_energy = serializers.SerializerMethodField()

    def get_generation_power(self, obj):
        return float(obj.get('total_solar_generation', 0) or 0)

    def get_battery_soc(self, obj):
        return float(obj.get('battery_soc', 0) or 0)

    def get_grid_power(self, obj):
        return float(obj.get('total_grid_consumption', 0) or 0)

    def get_load_power(self, obj):
        return float(obj.get('total_load_power', 0) or 0)

    def get_daily_energy(self, obj):
        return float(obj.get('daily_energy', 0) or 0)

    def get_total_energy(self, obj):
        return float(obj.get('total_energy', 0) or 0)



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
