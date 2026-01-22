"""
Professional Admin Dashboard Views
Analytics and management interface for administrators.
"""
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.db.models import Count, Sum, Avg, Max, Min
from django.utils import timezone
from datetime import timedelta
import json

from ..charging_stations.models import Station
from ..api.energy.models import Inverter, InverterReading, EVChargingSession
from ..accounts.models import UserProfile


@staff_member_required
def admin_dashboard(request):
    """
    Professional admin dashboard with comprehensive analytics.
    """
    # Time ranges
    now = timezone.now()
    today = now.date()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    
    # Station Statistics
    station_stats = {
        'total': Station.objects.count(),
        'active': Station.objects.filter(status='active').count(),
        'inactive': Station.objects.filter(status='inactive').count(),
        'maintenance': Station.objects.filter(status='maintenance').count(),
    }
    
    # Transaction Statistics (simplified since Transaction model doesn't exist yet)
    transaction_stats = {
        'today': 0,  # Will be implemented when Transaction model exists
        'this_week': 0,
        'this_month': 0,
        'total': 0,
        'active': 0,
    }
    
    # Energy Statistics (simplified)
    energy_stats = {
        'today_kwh': 0,  # Will be implemented when Transaction model exists
        'week_kwh': 0,
        'month_kwh': 0,
        'total_kwh': 0,
    }
    
    # Inverter Statistics
    inverter_stats = {
        'total': Inverter.objects.count(),
        'active': Inverter.objects.filter(is_active=True).count(),
        'with_data': Inverter.objects.filter(
            inverterreading__timestamp__gte=timezone.now() - timedelta(hours=1)
        ).distinct().count(),
    }
    
    # Recent Activity
    recent_readings = InverterReading.objects.order_by('-timestamp')[:10]
    recent_stations = Station.objects.order_by('-last_seen')[:10]
    
    # System Health
    system_health = {
        'stations_with_recent_data': Station.objects.filter(
            last_seen__gte=timezone.now() - timedelta(hours=24)
        ).count(),
        'inverters_with_recent_data': Inverter.objects.filter(
            inverterreading__timestamp__gte=timezone.now() - timedelta(hours=1)
        ).distinct().count(),
        'active_sessions': 0,  # Will be implemented when Transaction model exists
    }
    
    context = {
        'station_stats': station_stats,
        'transaction_stats': transaction_stats,
        'energy_stats': energy_stats,
        'inverter_stats': inverter_stats,
        'recent_stations': recent_stations,
        'recent_readings': recent_readings,
        'system_health': system_health,
        'title': 'Admin Dashboard',
    }
    
    return render(request, 'admin/dashboard.html', context)


@staff_member_required
def data_management(request):
    """
    Data management interface for professional administration.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'cleanup_old_readings':
            # Clean up readings older than 30 days
            cutoff_date = timezone.now() - timedelta(days=30)
            deleted_count = InverterReading.objects.filter(
                timestamp__lt=cutoff_date
            ).delete()[0]
            
            return render(request, 'admin/data_management.html', {
                'message': f'Deleted {deleted_count} old readings',
                'message_type': 'success'
            })
        
        elif action == 'reset_sequences':
            # Reset sequences (development only)
            from renew_website.utils.sequence_manager import SequenceManager
            
            models_to_reset = [Inverter, InverterReading, Transaction]
            results = {}
            
            for model in models_to_reset:
                success = SequenceManager.reset_sequence(model, 1)
                results[model.__name__] = 'Success' if success else 'Failed'
            
            return render(request, 'admin/data_management.html', {
                'message': f'Sequence reset results: {results}',
                'message_type': 'info'
            })
    
    # Get data statistics
    data_stats = {
        'inverter_readings': InverterReading.objects.count(),
        'stations': Station.objects.count(),
        'charging_sessions': EVChargingSession.objects.count(),
        'oldest_reading': InverterReading.objects.aggregate(
            oldest=Min('timestamp')
        )['oldest'],
        'newest_reading': InverterReading.objects.aggregate(
            newest=Max('timestamp')
        )['newest'],
    }
    
    context = {
        'data_stats': data_stats,
        'title': 'Data Management',
    }
    
    return render(request, 'admin/data_management.html', context)


@staff_member_required
def system_settings(request):
    """
    System settings and configuration management.
    """
    if request.method == 'POST':
        # Handle settings updates
        pass
    
    # Get current settings
    from django.conf import settings
    
    system_settings = {
        'debug': settings.DEBUG,
        'database_engine': settings.DATABASES['default']['ENGINE'],
        'timezone': settings.TIME_ZONE,
        'language_code': settings.LANGUAGE_CODE,
        'installed_apps': len(settings.INSTALLED_APPS),
    }
    
    context = {
        'system_settings': system_settings,
        'title': 'System Settings',
    }
    
    return render(request, 'admin/system_settings.html', context)
