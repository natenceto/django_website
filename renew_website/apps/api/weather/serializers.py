from rest_framework import serializers
from .models import WeatherLog

class WeatherLogSerializer(serializers.ModelSerializer):
    """Serializer for WeatherLog model."""
    class Meta:
        model = WeatherLog
        fields = [
            'timestamp', 'temp_c', 'humidity', 
            'cloud_cover', 'wind_kph', 'pressure_hpa', 
            'precipitation_mm', 'irradiance_wm2', 'source'
        ]
