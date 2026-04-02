from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.contrib import messages
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
    
    # Override status based on actual WebSocket connections
    for station in stations_list:
        # Check if station is actually connected via WebSocket
        station_id_str = str(station.id)
        station_id_int = station.id
        is_connected = station_id_str in ACTIVE_STATIONS or station_id_int in ACTIVE_STATIONS
        
        if not is_connected:
            # Station is not connected - show as inactive regardless of DB status
            station.status = 'inactive'

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
            valid_rfid = UserRFID.objects.first()
            if not valid_rfid:
                # Create a default RFID tag for testing
                valid_rfid = UserRFID.objects.create(
                    tag="19",
                    owner_name="Default Test Tag"
                )
                print(f"Created default RFID tag: {valid_rfid.tag}")
            
            results = []
            success_count = 0
            error_count = 0
            
            for station_id in station_ids:
                # Convert station_id to int for ACTIVE_STATIONS lookup
                station_id = int(station_id)
                
                print(f"Processing station {station_id}, ACTIVE_STATIONS keys: {list(ACTIVE_STATIONS.keys())}")
                
                # Check if station is connected
                if station_id not in ACTIVE_STATIONS:
                    results.append(f"Station {station_id}: Not connected")
                    error_count += 1
                    print(f"Station {station_id} not in ACTIVE_STATIONS")
                    continue
                
                consumer = ACTIVE_STATIONS[station_id]
                print(f"Found consumer for station {station_id}")
                
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

                        # Send RemoteStartTransaction command
                        power_msg = f"{power_limit}kW" if power_limit else "Auto (unlimited)"
                        print(f"Sending RemoteStartTransaction to station {station_id}: connector={connector.connector_id}, id_tag={valid_rfid.tag}, power={power_msg}")
                        
                        try:
                            # Send the command with proper response handling
                            
                            response = async_to_sync(consumer.cp.call_remote_start_transaction)(
                                connector_id=connector.connector_id,
                                id_tag=valid_rfid.tag,
                                requested_power=power_limit
                            )
                            
                            print(f"RemoteStartTransaction response: {response}")
                            
                            # Check response status
                            if hasattr(response, 'status') and response.status == "Accepted":
                                power_str = f"{power_limit} kW" if power_limit else "Auto"
                                results.append(f"Station {station_id}: Charging session started ({power_str})")
                                success_count += 1
                            else:
                                status_msg = getattr(response, 'status', 'Unknown')
                                results.append(f"Station {station_id}: Start rejected - {status_msg}")
                                error_count += 1
                            
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
                            response = async_to_sync(consumer.cp.call_remote_stop_transaction)(
                                transaction_id=active_transaction.id
                            )
                            
                            if response.status == "Accepted":
                                results.append(f"Station {station_id}: Charging session stopped")
                                success_count += 1
                            else:
                                results.append(f"Station {station_id}: Stop rejected - {response.status}")
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
