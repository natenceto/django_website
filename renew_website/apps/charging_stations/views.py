from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import StationForm
from .models import Station
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.template.loader import render_to_string

def stations(request: HttpRequest) -> HttpResponse:
    """
    Two-tab view:
    - Add Station form
    - View Stations tab (with actions for multiple stations)
    Implements Post/Redirect/Get pattern to avoid form resubmission
    and keeps current tab on refresh.
    """
    from .consumers import ACTIVE_STATIONS
    from .models import Transaction, Connector
    from django.db.models import Sum
    from django.utils import timezone
    from datetime import timedelta
    
    form = StationForm(request.POST or None)
    stations_list = list(Station.objects.all().prefetch_related('connectors'))
    
    # Calculate dashboard statistics
    total_stations = len(stations_list)
    online_stations = len([s for s in stations_list if s.id in ACTIVE_STATIONS or str(s.id) in ACTIVE_STATIONS])
    active_sessions = Transaction.objects.filter(status='active').count()
    
    # Energy delivered today
    today = timezone.now().date()
    today_transactions = Transaction.objects.filter(
        started_at__date=today,
        meter_stop__isnull=False
    )
    energy_today_wh = today_transactions.aggregate(
        total=Sum('meter_stop') - Sum('meter_start')
    )['total'] or 0
    energy_today_kwh = round(energy_today_wh / 1000, 1)
    
    stats = {
        'total_stations': total_stations,
        'online_stations': online_stations,
        'active_sessions': active_sessions,
        'energy_today_kwh': energy_today_kwh,
    }
    
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
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            
            print(f"=== Action received: {action}, stations: {station_ids}, ajax: {is_ajax} ===")

            if not station_ids:
                message = "No station selected."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
                return redirect(f"{request.path}?tab=list")

            from .consumers import ACTIVE_STATIONS
            from .models import UserRFID, Transaction, Connector
            from datetime import datetime, timezone
            
            # Get a valid RFID tag from the database, create one if none exists
            valid_rfid = UserRFID.objects.filter(tag="000000010160897").first()
            if not valid_rfid:
                # Create the specific RFID tag for testing
                valid_rfid = UserRFID.objects.create(
                    tag="000000010160897",
                    owner_name="Default Test Tag"
                )
                print(f"Created default RFID tag: {valid_rfid.tag}")
            else:
                print(f"Using existing RFID tag: {valid_rfid.tag}")
            
            results = []
            success_count = 0
            error_count = 0
            
            for station_id in station_ids:
                # Convert station_id to int for database lookup
                station_id = int(station_id)
                
                print(f"Processing station {station_id}, ACTIVE_STATIONS keys: {list(ACTIVE_STATIONS.keys())}")
                
                # Don't check connection status - just try to send the command
                # The station will handle it if it's connected, or fail gracefully if not
                # This avoids issues with database status not being updated in time
                
                # Use channel layer to send message to station consumer
                # This works even if ACTIVE_STATIONS is empty (multi-process issue)
                group_name = f"charging_stations_group_{station_id}"
                try:
                    if action == "start":
                        # Single-connector stations use connector_id = 1 per OCPP
                        connector = Connector.objects.filter(station_id=station_id, connector_id=1).first()
                        if not connector:
                            # Not yet reported by the station
                            results.append(f"Station {station_id}: Connector 1 not discovered yet. Wait for station boot/status to report connector 1.")
                            error_count += 1
                            continue
                        
                        # Get requested power from UI, or use station's max power as default
                        requested_power = request.POST.get("power")
                        power_limit = None
                        if requested_power and requested_power.lower() == 'auto':
                            print(f"Station {station_id}: Requested 'Auto' power - leaving it to EV to negotiate")
                            power_limit = None # No TxProfile will be created in consumer.py
                        elif requested_power:
                            power_limit = int(requested_power)
                        else:
                            # Default to station's maximum power output
                            station = Station.objects.get(id=station_id)
                            power_limit = station.power_output

                        # Send RemoteStartTransaction command via channel layer
                        power_msg = f"{power_limit}kW" if power_limit else "Auto (unlimited)"
                        print(f"Sending RemoteStartTransaction to station {station_id}: connector={connector.connector_id}, id_tag={valid_rfid.tag}, power={power_msg}")
                        
                        try:
                            # Use channel layer to send command to station consumer
                            from channels.layers import get_channel_layer
                            channel_layer = get_channel_layer()
                            
                            message = {
                                "type": "remote_start_transaction",
                                "connector_id": connector.connector_id,
                                "id_tag": valid_rfid.tag,
                                "requested_power": power_limit,
                                "station_id": station_id,
                            }
                            
                            print(f"Sending message via channel layer to group charging_stations_group_{station_id}: {message}")
                            
                            # Send command via channel layer
                            async_to_sync(channel_layer.group_send)(
                                f"charging_stations_group_{station_id}",
                                message
                            )
                            
                            print(f"Message sent successfully")
                            
                            results.append(f"Station {station_id}: RemoteStartTransaction sent successfully")
                            success_count += 1
                            
                        except Exception as e:
                            print(f"RemoteStartTransaction failed: {e}")
                            import traceback
                            traceback.print_exc()
                            results.append(f"Station {station_id}: Failed to start charging - {str(e)}")
                            error_count += 1
                    
                    elif action == "stop":
                        # Find the active transaction for this station
                        active_transaction = Transaction.objects.filter(
                            connector__station_id=station_id,
                            status="active"
                        ).first()
                        
                        if active_transaction:
                            print(f"Stopping transaction {active_transaction.id} for station {station_id}")
                            
                            try:
                                # Use channel layer to send command to station consumer
                                from channels.layers import get_channel_layer
                                channel_layer = get_channel_layer()
                                
                                message = {
                                    "type": "remote_stop_transaction",
                                    "transaction_id": active_transaction.id,
                                    "station_id": station_id,
                                }
                                
                                print(f"Sending stop message via channel layer to group charging_stations_group_{station_id}: {message}")
                                
                                # Send command via channel layer
                                async_to_sync(channel_layer.group_send)(
                                    f"charging_stations_group_{station_id}",
                                    message
                                )
                                
                                print(f"Stop message sent successfully")
                                
                                results.append(f"Station {station_id}: Stop command sent")
                                success_count += 1
                                
                            except Exception as e:
                                print(f"Stop transaction failed: {e}")
                                import traceback
                                traceback.print_exc()
                                results.append(f"Station {station_id}: Failed to stop charging - {str(e)}")
                                error_count += 1
                        else:
                            results.append(f"Station {station_id}: No active charging session")
                            error_count += 1
                    
                    elif action == "apply_power":
                        power = request.POST.get("power", "11")
                        # TODO: Implement ChangeConfiguration for charging power
                        results.append(f"Station {station_id}: Power set to {power} kW (not implemented)")
                        success_count += 1
                    
                    else:
                        results.append(f"Unknown action: {action}")
                        error_count += 1
                
                except Exception as e:
                    error_msg = str(e)
                    # Check if it's a timeout (unsupported command by simulator)
                    if "Waited 30s for response" in error_msg or "timeout" in error_msg.lower():
                        results.append(f"Station {station_id}: Command not supported by simulator/station")
                    else:
                        results.append(f"Station {station_id}: Error - {error_msg}")
                    error_count += 1

            # Prepare response message
            message = '<br>'.join(results)
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
        from django.db.models import Prefetch, Count, Max

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


@login_required
def export_charging_sessions_csv(request):
    """Export charging sessions as CSV."""
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="charging_sessions.csv"'
    
    writer = csv.writer(response)
    
    # Get data from last 30 days
    from datetime import timedelta
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    
    transactions = Transaction.objects.filter(
        started_at__range=[start_date, end_date]
    ).select_related('connector__station').order_by('-started_at')
    
    # Write header
    writer.writerow([
        'ID', 'Station', 'Connector', 'Vehicle ID', 
        'Start Time', 'End Time', 'Duration (minutes)',
        'Energy (kWh)', 'Requested Power (kW)', 'Status'
    ])
    
    # Write data
    for transaction in transactions:
        writer.writerow([
            transaction.id,
            transaction.connector.station.address,
            transaction.connector.connector_id,
            transaction.id_tag,
            transaction.started_at.strftime('%Y-%m-%d %H:%M:%S'),
            transaction.stopped_at.strftime('%Y-%m-%d %H:%M:%S') if transaction.stopped_at else '',
            transaction.duration_minutes or '',
            transaction.energy_kwh or 0,
            transaction.requested_power_kw or 0,
            transaction.status
        ])
    
    return response
