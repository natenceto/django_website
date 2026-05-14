from django.contrib import admin
from .models import Station, StationStatusHistory, Connector, Transaction, MeterValue, UserRFID, CommandLog, Vehicle


from django.utils.html import format_html
from django.utils import timezone

@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'formatted_serial_column', 
        'runtime_environment',
        'status_badge', 
        'connector_status', 
        'last_seen_column',
        'short_address_with_tooltip',
    ]
    list_filter = ['status', 'runtime_environment', 'connector_type']
    search_fields = [
        'serial_number', 
        'address', 
        'email',
        'connectors__vendor_connector_id'
    ]
    ordering = ['id']  # Show oldest first (natural order)
    
    def formatted_serial_column(self, obj):
        return obj.formatted_serial()
    formatted_serial_column.short_description = 'Model/Serial'
    formatted_serial_column.admin_order_field = 'serial_number'
    
    def short_address_with_tooltip(self, obj):
        return format_html(
            '<span title="{}">{}</span>',
            obj.address,
            obj.short_address()
        )
    short_address_with_tooltip.short_description = 'Address'
    
    def last_seen_column(self, obj):
        if not obj.last_seen:
            return "Never"
            
        now = timezone.now()
        delta = now - obj.last_seen
        
        if delta.total_seconds() < 60:  # Less than a minute
            return "Just now"
        elif delta.total_seconds() < 3600:  # Less than an hour
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m ago"
        elif delta.total_seconds() < 86400:  # Less than a day
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        else:  # More than a day
            days = delta.days
            return f"{days}d ago"
    last_seen_column.short_description = 'Last Seen'
    last_seen_column.admin_order_field = 'last_seen'
    
    def connector_status(self, obj):
        # Get all connectors for this station
        connectors = obj.connectors.all()
        if not connectors:
            return "No connectors"
            
        # Count statuses
        status_counts = {}
        for conn in connectors:
            status_counts[conn.status] = status_counts.get(conn.status, 0) + 1
            
        # Format the status string
        status_parts = []
        for status, count in status_counts.items():
            if count > 1:
                status_parts.append(f"{count}×{status}")
            else:
                status_parts.append(status)
                
        return ", ".join(status_parts)
    connector_status.short_description = 'Connector Status'


@admin.register(StationStatusHistory)
class StationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ['station', 'status', 'reason', 'observed_at']
    list_filter = ['status', 'reason', 'observed_at']
    search_fields = ['station__address', 'station__ocpp_identity', 'reason']
    date_hierarchy = 'observed_at'
    ordering = ['-observed_at']


@admin.register(Connector)
class ConnectorAdmin(admin.ModelAdmin):
    list_display = ['id', 'station', 'connector_id', 'status']
    list_filter = ['status']
    search_fields = ['station__address']
    ordering = ['station', 'connector_id']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """OCPP Transaction Admin - Core charging session management."""
    list_display = [
        'id', 'transaction_id', 'vehicle', 'id_tag', 'connector', 
        'requested_power_mode', 'requested_power_kw', 'latest_actual_power_display',
        'last_applied_ems_limit_kw', 'status', 'started_at', 'duration_display', 'energy_display'
    ]
    list_filter = ['status', 'started_at']
    search_fields = ['id_tag', 'vehicle__vehicle_identifier', 'vehicle__vin', 'vehicle__registration_number', 'connector__station__address', 'transaction_id']
    date_hierarchy = 'started_at'
    readonly_fields = ['started_at', 'energy_consumed', 'duration', 'latest_actual_power_display']
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('transaction_id', 'vehicle', 'id_tag', 'connector', 'status')
        }),
        ('Timing', {
            'fields': ('started_at', 'stopped_at')
        }),
        ('Energy Data', {
            'fields': ('meter_start', 'meter_stop', 'requested_power_mode', 'requested_power_kw', 'last_applied_ems_limit_kw', 'latest_actual_power_display', 'energy_consumed')
        }),
        ('Cost', {
            'fields': ('cost', 'pricing_plan'),
            'classes': ('collapse',)
        }),
    )
    
    def duration_display(self, obj):
        """Display formatted duration."""
        duration = obj.duration
        if duration:
            total_seconds = int(duration.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if hours > 0:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"
        return "Active" if obj.status == 'active' else "N/A"
    duration_display.short_description = 'Duration'
    
    def energy_display(self, obj):
        """Display formatted energy."""
        energy = obj.energy_consumed
        if energy is not None:
            return f"{energy:.2f} kWh"
        return "N/A"
    energy_display.short_description = 'Energy'

    def latest_actual_power_display(self, obj):
        latest_power_kw = obj.latest_actual_power_kw
        if latest_power_kw is None:
            return "N/A"
        return f"{latest_power_kw:.2f} kW"
    latest_actual_power_display.short_description = 'Actual Power'


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = [
        'vehicle_identifier', 'registration_number', 'vin', 'manufacturer',
        'model_name', 'model_year', 'last_known_soc_percent', 'battery_capacity_kwh', 'last_seen_at'
    ]
    list_filter = ['manufacturer', 'model_year', 'created_at', 'last_seen_at']
    search_fields = ['vehicle_identifier', 'registration_number', 'vin', 'manufacturer', 'model_name', 'trim', 'color']
    readonly_fields = ['created_at', 'updated_at', 'first_seen_at', 'last_seen_at']
    fieldsets = (
        ('Identity', {
            'fields': ('vehicle_identifier', 'vin', 'registration_number')
        }),
        ('Vehicle Details', {
            'fields': ('manufacturer', 'model_name', 'model_year', 'trim', 'color', 'battery_capacity_kwh', 'last_known_soc_percent')
        }),
        ('Metadata', {
            'fields': ('metadata', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(MeterValue)
class MeterValueAdmin(admin.ModelAdmin):
    list_display = ['transaction', 'timestamp', 'power_w', 'energy_wh', 'soc_percentage', 'value']
    list_filter = ['timestamp']
    date_hierarchy = 'timestamp'


@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    list_display = ['command_id', 'command_type', 'station', 'status', 'created_at', 'executed_at']
    list_filter = ['command_type', 'status', 'created_at']
    search_fields = ['command_id', 'station__address', 'detail', 'error_message']
    readonly_fields = ['command_id', 'created_at', 'executed_at', 'payload']
    date_hierarchy = 'created_at'


from django.urls import path
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse

@admin.register(UserRFID)
class UserRFIDAdmin(admin.ModelAdmin):
    list_display = ('tag', 'owner_name', 'is_active', 'created_at', 'stations_list')
    list_filter = ('is_active', 'created_at', 'stations')
    search_fields = ('tag', 'owner_name', 'notes')
    filter_horizontal = ('stations',)
    readonly_fields = ('created_at', 'last_updated')
    list_per_page = 20
    
    fieldsets = (
        ('RFID Information', {
            'fields': ('tag', 'owner_name', 'is_active')
        }),
        ('Access Control', {
            'fields': ('stations',),
            'description': 'Select which stations this RFID can access'
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at', 'last_updated'),
            'classes': ('collapse',)
        }),
    )
    
    def stations_list(self, obj):
        return ", ".join([station.formatted_serial() for station in obj.stations.all()])
    stations_list.short_description = 'Authorized Stations'
    
    def actions_column(self, obj):
        return format_html(
            '<div class="action-buttons">'
            '<a class="button" href="{}">Edit</a> '
            '<a class="button" href="{}" style="color:red;">Delete</a>'
            '</div>',
            reverse('admin:charging_stations_userrfid_change', args=[obj.id]),
            reverse('admin:charging_stations_userrfid_delete', args=[obj.id])
        )
    actions_column.short_description = 'Actions'
    actions_column.allow_tags = True
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:rfid_id>/toggle-active/',
                self.admin_site.admin_view(self.toggle_active),
                name='userrfid-toggle-active',
            ),
            path(
                'bulk-delete/',
                self.admin_site.admin_view(self.bulk_delete),
                name='userrfid-bulk-delete',
            ),
        ]
        return custom_urls + urls
    
    def toggle_active(self, request, rfid_id):
        try:
            rfid = UserRFID.objects.get(id=rfid_id)
            rfid.is_active = not rfid.is_active
            rfid.save()
            messages.success(request, f'RFID {rfid.tag} is now {"active" if rfid.is_active else "inactive"}')
        except UserRFID.DoesNotExist:
            messages.error(request, 'RFID not found')
        return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/admin/'))
    
    def bulk_delete(self, request):
        if request.method == 'POST':
            rfid_ids = request.POST.getlist('_selected_action')
            if rfid_ids:
                deleted, _ = UserRFID.objects.filter(id__in=rfid_ids).delete()
                messages.success(request, f'Successfully deleted {deleted} RFID(s)')
            else:
                messages.error(request, 'No RFIDs selected')
            return redirect('admin:charging_stations_userrfid_changelist')
        return render(request, 'admin/confirm_bulk_delete.html', {'title': 'Delete multiple RFIDs'})
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('stations')
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.last_updated = timezone.now()
        super().save_model(request, obj, form, change)
    
    def delete_model(self, request, obj):
        messages.info(request, f'RFID {obj.tag} has been deleted')
        super().delete_model(request, obj)
    
    class Media:
        css = {
            'all': ('admin/css/userrfid_admin.css',)
        }

from .models import PricingPlan, StationPricing, ChargingSession, PaymentMethod, Invoice
from django.contrib.auth import get_user_model

@admin.register(PricingPlan)
class PricingPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'price_per_kwh', 'currency', 'is_active']
    list_filter = ['currency', 'is_active']
    search_fields = ['name']

@admin.register(StationPricing)
class StationPricingAdmin(admin.ModelAdmin):
    list_display = ['station', 'pricing_plan', 'is_default']
    list_filter = ['is_default']
    autocomplete_fields = ['station', 'pricing_plan']

@admin.register(ChargingSession)
class ChargingSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_info', 'total_cost', 'currency', 'created_at']
    list_filter = ['currency', 'created_at']
    
    def user_info(self, obj):
        if obj.user_id:
            try:
                User = get_user_model()
                user = User.objects.using('default').get(pk=obj.user_id)
                return f"{user.username} ({obj.user_id})"
            except Exception:
                return f"User ID {obj.user_id}"
        return "-"
    user_info.short_description = "User"

@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['id', 'type', 'print_user', 'is_default']
    
    def print_user(self, obj):
         return f"User ID {obj.user_id}"
    print_user.short_description = "User"

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'user_id', 'total', 'status', 'issue_date']
    list_filter = ['status']
