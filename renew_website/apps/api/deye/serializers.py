"""
Deye API Serializers.
Поддържа Cloud и Local източници чрез Manager.
"""
from rest_framework import serializers

class BaseInverterSerializer(serializers.Serializer):
    """
    Общ за данни между Backend и Frontend.
    """
    device_sn = serializers.CharField()
    source = serializers.CharField(required=False)
    
    # Основни метрики (Нормализирани)
    generation_power = serializers.FloatField(default=0.0)
    battery_soc = serializers.FloatField(default=0.0)
    grid_power = serializers.FloatField(default=0.0) 
    load_power = serializers.FloatField(default=0.0)
    
    daily_energy = serializers.FloatField(default=0.0)
    monthly_energy = serializers.FloatField(default=0.0)
    total_energy = serializers.FloatField(default=0.0)
    capacity = serializers.FloatField(default=0.0)

class DeyeCloudSerializer(BaseInverterSerializer):
    """
    Сериализатор за данни от Deye Cloud API.
    """
    generation_power = serializers.SerializerMethodField()
    battery_soc = serializers.SerializerMethodField()
    grid_power = serializers.SerializerMethodField()
    load_power = serializers.SerializerMethodField()
    daily_energy = serializers.SerializerMethodField()
    monthly_energy = serializers.SerializerMethodField()
    total_energy = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()

    def get_generation_power(self, obj):
        if 'generationPower' in obj: return float(obj['generationPower'])
        return self._find_in_datalist(obj, ['TotalSolarPower', 'ActivePower', 'Pac'])

    def get_battery_soc(self, obj):
        if 'batterySOC' in obj: return float(obj['batterySOC'])
        return self._find_in_datalist(obj, ['BatterySOC', 'SOC'])

    def get_grid_power(self, obj):
        if 'gridPower' in obj: return float(obj['gridPower'])
        return self._find_in_datalist(obj, ['GridActivePower', 'TotalGridPower'])
        
    def get_load_power(self, obj):
        # Облакът често не дава Load Power директно
        return self._find_in_datalist(obj, ['TotalLoadPower', 'LoadPower', 'CustomerLoad'])

    def get_daily_energy(self, obj):
        if 'dailyEnergy' in obj: return float(obj['dailyEnergy'])
        return self._find_in_datalist(obj, ['DailyActiveProduction', 'DailyEnergy', 'TodayYield'])

    def get_total_energy(self, obj):
        if 'totalEnergy' in obj: return float(obj['totalEnergy'])
        return self._find_in_datalist(obj, ['TotalActiveProduction', 'TotalEnergy', 'TotalYield'])

    def get_monthly_energy(self, obj):
        if 'monthlyEnergy' in obj: return float(obj['monthlyEnergy'])
        return self._find_in_datalist(obj, ['MonthlyActiveProduction', 'MonthlyEnergy', 'MonthYield'])

    def get_capacity(self, obj):
        if 'capacity' in obj: return float(obj['capacity'])
        return self._find_in_datalist(obj, ['InstalledCapacity', 'Capacity', 'PlantCapacity'])

    def _find_in_datalist(self, obj, keys):
        data_list = obj.get('dataList', [])
        for item in data_list:
            if item.get('key') in keys:
                return float(item.get('value', 0))
        return 0.0

class DeyeLocalSerializer(BaseInverterSerializer):
    """
    Сериализатор за локални Modbus данни.
    Мапва различни версии на имената на регистрите към стандартни полета.
    """
    generation_power = serializers.SerializerMethodField()
    battery_soc = serializers.SerializerMethodField()
    grid_power = serializers.SerializerMethodField()
    load_power = serializers.SerializerMethodField()
    daily_energy = serializers.SerializerMethodField()
    monthly_energy = serializers.SerializerMethodField()
    total_energy = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()

    def get_generation_power(self, obj):
        return float(
            obj.get('total_solar_generation') or 
            obj.get('total_pv_power') or 
            obj.get('pv_power') or 
            obj.get('total_from_pv') or 0
        )

    def get_battery_soc(self, obj):
        return float(obj.get('battery_soc') or 0)

    def get_grid_power(self, obj):
        return float(
            obj.get('total_grid_power') or 
            obj.get('total_buy_grid') or 
            obj.get('grid_power') or 0
        )

    def get_load_power(self, obj):
        return float(
            obj.get('total_load_power') or 
            obj.get('load_power') or 
            obj.get('total_to_load') or 0
        )

    def get_daily_energy(self, obj):
        return float(obj.get('daily_energy') or 0)

    def get_total_energy(self, obj):
        return float(obj.get('total_energy') or 0)

    def get_monthly_energy(self, obj):
        return float(obj.get('monthly_energy') or obj.get('month_energy') or 0)

    def get_capacity(self, obj):
        return float(obj.get('capacity') or obj.get('installed_capacity') or obj.get('capacity_kwp') or 0)