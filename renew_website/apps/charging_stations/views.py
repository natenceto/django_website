from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.contrib import messages
from .forms import StationForm
from .models import Station
from django.template.loader import render_to_string
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .services import execute_station_action


def _build_station_stats(stations_list):
    from .consumers import ACTIVE_STATIONS
    from .models import Transaction
    from django.db.models import Sum
    from django.utils import timezone

    total_stations = len(stations_list)
    online_stations = sum(
        1 for station in stations_list if station.id in ACTIVE_STATIONS or str(station.id) in ACTIVE_STATIONS
    )
    active_sessions = Transaction.objects.filter(status='active').count()

    today = timezone.now().date()
    today_transactions = Transaction.objects.filter(
        started_at__date=today,
        meter_stop__isnull=False,
    )
    energy_today_wh = today_transactions.aggregate(total=Sum('meter_stop') - Sum('meter_start'))['total'] or 0

    return {
        'total_stations': total_stations,
        'online_stations': online_stations,
        'active_sessions': active_sessions,
        'energy_today_kwh': round(energy_today_wh / 1000, 1),
    }

def stations(request: HttpRequest) -> HttpResponse:
    """
    Two-tab view:
    - Add Station form
    - View Stations tab (with actions for multiple stations)
    Implements Post/Redirect/Get pattern to avoid form resubmission
    and keeps current tab on refresh.
    """
    form = StationForm(request.POST or None)
    stations_list = list(Station.objects.all().prefetch_related('connectors'))

    stats = _build_station_stats(stations_list)

    # Keep original status from database - don't override based on WebSocket connections
    # The WebSocket will update the status in real-time via JavaScript

    # Определяме текущия активен таб според query параметър
    active_tab = request.GET.get("tab", "add")

    if request.method == "POST":
        # Скрито поле във формата за текущ таб
        current_tab = request.POST.get("current_tab", "add")

        # --- Add Station Form POST ---
        if "address" in request.POST:  # едно от полетата на StationForm
            if form.is_valid():
                station = form.save()
                
                stations_list = Station.objects.all()

                # Notify WebSocket group (ако се използва)
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "charging_stations_group",
                    {
                        "type": "station.message",
                        "html": render_to_string(
                            "charging_stations/_stations_tab.html",
                            {"stations_list": stations_list}
                        )
                    }
                )

                messages.success(request, f"Station {station.address} added successfully!")
                # След POST redirect към list tab
                return redirect(f"{request.path}?tab=list")
            else:
                messages.error(request, "Please correct the errors below.")
                active_tab = current_tab

        # --- Action buttons POST (start/stop) ---
        elif "action" in request.POST:
            station_ids = request.POST.getlist("station_ids")
            action = request.POST.get("action")
            power = request.POST.get("power")
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            if not station_ids:
                message = "No station selected."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
                return redirect(f"{request.path}?tab=list")

            success_count, error_count, message = execute_station_action(
                action=action,
                station_ids=station_ids,
                power=power,
            )
            overall_success = success_count > 0 and error_count == 0
            
            if is_ajax:
                return JsonResponse({
                    'success': overall_success,
                    'message': message,
                    'success_count': success_count,
                    'error_count': error_count
                })
            
            # Non-AJAX response
            if overall_success:
                messages.success(request, message)
            elif success_count > 0:
                messages.warning(request, message)
            else:
                messages.error(request, message)
            
            return redirect(f"{request.path}?tab=list")

    # --- GET request ---
    return render(
        request,
        "charging_stations/stations.html",
        {
            "form": form,
            "stations_list": stations_list,
            "active_tab": active_tab,
            "stats": stats,
        }
    )


def statistics(request: HttpRequest) -> HttpResponse:
    """
    Display comprehensive charging station statistics and meter measurements.
    Shows real-time data from all active charging sessions and historical measurements.
    """
    try:
        from .models import MeterValue, Transaction
        from django.db.models import Count, Max

        # Calculate summary statistics FIRST (before any slicing)
        total_readings = MeterValue.objects.count()
        active_sessions = Transaction.objects.filter(status='active').count()
        latest_reading = MeterValue.objects.order_by('-timestamp').first()

        # Get recent transactions with optimized queries (avoid slicing in prefetch)
        transactions = Transaction.objects.select_related(
            'connector__station'
        ).annotate(
            meter_count=Count('meter_values'),
            latest_reading=Max('meter_values__value')
        ).order_by('-started_at')[:20]  # Last 20 transactions for better performance

        # Prefetch meter values separately to avoid slicing issues
        for transaction in transactions:
            transaction.prefetched_meter_values = list(
                transaction.meter_values.order_by('-timestamp')[:10]
            )

        # Get recent meter values with station info (separate queryset)
        meter_values = MeterValue.objects.select_related(
            'transaction__connector__station'
        ).order_by('-timestamp')[:50]  # Last 50 readings for dashboard

        context = {
            'transactions': transactions,
            'meter_values': meter_values,
            'total_readings': total_readings,
            'active_sessions': active_sessions,
            'latest_reading': latest_reading,
        }

        return render(request, "charging_stations/statistics.html", context)

    except Exception as e:
        # Handle any database errors gracefully
        context = {
            'transactions': [],
            'meter_values': [],
            'error_message': f"Unable to load statistics: {str(e)}"
        }
        return render(request, "charging_stations/statistics.html", context)


def tables(request: HttpRequest) -> HttpResponse:
    return render(request, "charging_stations/tables.html")

def get_current_soc(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)

def get_soc_history(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)

def update_station_soc_config(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)
