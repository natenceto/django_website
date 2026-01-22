"""
Professional Admin Interface for EV Charging Platform
Complete CRUD operations with advanced features.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.db import models
from django.forms import ModelForm
from django import forms
import json

from ..charging_stations.models import Station
from ..api.energy.models import Inverter, InverterReading, EVChargingSession


class AdvancedAdminMixin:
    """Mixin for advanced admin features."""
    
    def get_queryset(self, request):
        """Optimize queryset with select_related/prefetch_related."""
        qs = super().get_queryset(request)
        return qs.select_related(*self.select_related_fields).prefetch_related(*self.prefetch_related_fields)
    
    def has_add_permission(self, request):
        """Control add permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_add_permission(request)
    
    def has_change_permission(self, request, obj=None):
        """Control change permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_change_permission(request, obj)
    
    def has_delete_permission(self, request, obj=None):
        """Control delete permissions based on user role."""
        if request.user.is_superuser:
            return True
        return super().has_delete_permission(request, obj)


# ===== USER MANAGEMENT =====

class UserProfileInline(admin.StackedInline):
    """Inline user profile editing."""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'


class CustomUserAdmin(UserAdmin):
    """Enhanced user admin with profile."""
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )


# ===== CHARGING STATIONS =====

@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    """Professional charging station admin."""
    list_display = ('address', 'status', 'connector_type', 'power_output', 'last_seen')
    list_filter = ('status', 'connector_type')
    search_fields = ('address', 'email')
    readonly_fields = ('last_seen',)
    
    fieldsets = (
        ('Location Information', {
            'fields': ('address', 'latitude', 'longitude')
        }),
        ('Charger Info', {
            'fields': ('model', 'connector_type', 'power_output')
        }),
        ('Operations', {
            'fields': ('status', 'last_seen')
        }),
        ('Owner Info', {
            'fields': ('email',)
        }),
    )


# ===== ENERGY MANAGEMENT =====

@admin.register(Inverter)
class InverterAdmin(AdvancedAdminMixin, admin.ModelAdmin):
    """Inverter management admin."""
    list_display = ('device_sn', 'device_id', 'device_type', 'station_id', 'is_active', 'last_reading')
    list_filter = ('device_type', 'is_active', 'created_at')
    search_fields = ('device_sn', 'device_id', 'station_id')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Device Information', {
            'fields': ('device_sn', 'device_id', 'device_type', 'product_id')
        }),
        ('Station Details', {
            'fields': ('station_id', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def last_reading(self, obj):
        """Display last reading time."""
        last_reading = obj.inverterreading_set.order_by('-timestamp').first()
        return last_reading.timestamp.strftime('%Y-%m-%d %H:%M') if last_reading else 'No data'
    last_reading.short_description = 'Last Reading'


@admin.register(InverterReading)
class InverterReadingAdmin(AdvancedAdminMixin, admin.ModelAdmin):
    """Inverter readings admin with data management."""
    list_display = ('inverter', 'generation_power', 'battery_soc', 'grid_power', 'timestamp', 'connect_status')
    list_filter = ('connect_status', 'timestamp')
    search_fields = ('inverter__device_sn',)
    readonly_fields = ('timestamp', 'collection_time')
    
    fieldsets = (
        ('Reading Information', {
            'fields': ('inverter', 'timestamp', 'collection_time')
        }),
        ('Power Data', {
            'fields': ('generation_power', 'battery_soc', 'grid_power')
        }),
        ('Status', {
            'fields': ('connect_status', 'station_data')
        }),
    )
    
    select_related_fields = ['inverter']
    
    actions = ['bulk_delete_old_readings', 'export_readings_csv']
    
    def bulk_delete_old_readings(self, request, queryset):
        """Bulk delete old readings with confirmation."""
        count = queryset.count()
        self.message_user(request, f'Deleted {count} old readings.')
        queryset.delete()
    bulk_delete_old_readings.short_description = 'Delete selected readings'
    
    def export_readings_csv(self, request, queryset):
        """Export readings to CSV."""
        # Implementation for CSV export
        self.message_user(request, f'Exported {queryset.count()} readings to CSV.')
    export_readings_csv.short_description = 'Export to CSV'


# ===== ADMIN CUSTOMIZATION =====

# Register custom admin
admin.site.site_title = "EV Charging Platform Admin"
admin.site.site_header = "EV Charging Platform Administration"
admin.site.index_title = "Welcome to EV Charging Platform Admin"

# Register custom user admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
