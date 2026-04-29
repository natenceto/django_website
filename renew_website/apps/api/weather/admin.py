"""
Django admin configuration for weather models.
"""
from django.contrib import admin
from .models import WeatherLog


@admin.register(WeatherLog)
class WeatherLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'temp_c', 'humidity', 'cloud_cover', 'wind_kph', 'irradiance_wm2', 'source']
    list_filter = ['source', 'timestamp']
    search_fields = ['source']
    readonly_fields = ['timestamp', 'raw_data']
    ordering = ['-timestamp']
    
    def get_queryset(self, request):
        return super().get_queryset(request)
