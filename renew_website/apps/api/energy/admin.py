"""
Django admin configuration for energy management models.
"""
from django.contrib import admin
from .models import Inverter, InverterReading, GridPricing


@admin.register(Inverter)
class InverterAdmin(admin.ModelAdmin):
    list_display = ['device_sn', 'device_type', 'station_id', 'is_active', 'updated_at']
    list_filter = ['device_type', 'is_active', 'station_id']
    search_fields = ['device_sn']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(InverterReading)
class InverterReadingAdmin(admin.ModelAdmin):
    list_display = ['inverter', 'timestamp', 'generation_power', 'battery_soc', 'connect_status']
    list_filter = ['connect_status', 'timestamp']
    search_fields = ['inverter__device_sn']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('inverter')


@admin.register(GridPricing)
class GridPricingAdmin(admin.ModelAdmin):
    list_display = ['start_time', 'end_time', 'price_per_kwh', 'is_peak']
    list_filter = ['is_peak']
    ordering = ['start_time']
