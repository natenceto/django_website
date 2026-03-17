from django.db import models
from django.utils import timezone

class WeatherLog(models.Model):
    """Historical weather data for algorithm training and retrospective."""
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    temp_c = models.FloatField(help_text="Temperature in Celsius")
    humidity = models.FloatField(help_text="Relative humidity %")
    cloud_cover = models.FloatField(help_text="Cloud cover % (0-100)")
    wind_kph = models.FloatField(help_text="Wind speed in km/h", default=0.0)
    pressure_hpa = models.FloatField(help_text="Atmospheric pressure in hPa", null=True, blank=True)
    precipitation_mm = models.FloatField(help_text="Precipitation in mm", default=0.0)
    # Solar irradiance is key for PV!
    irradiance_wm2 = models.FloatField(help_text="Global Horizontal Irradiance W/m2", null=True, blank=True)
    
    source = models.CharField(max_length=50, default="open-meteo")
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"Weather at {self.timestamp}: {self.temp_c}°C, {self.cloud_cover}% clouds"
