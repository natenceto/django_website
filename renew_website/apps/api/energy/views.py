"""
Energy management API views for EV charging optimization.
"""
import logging
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from django.shortcuts import render
from django.utils import timezone
from rest_framework.views import APIView

from .services import InverterDataService, EVChargingOptimizer
from .models import InverterReading, WorkMode, EnergyRecommendation
from .serializers import (
    InverterReadingSerializer, 
    DashboardDataSerializer,
    ChargingRecommendationRequestSerializer,
    ChargingRecommendationResponseSerializer,
    WorkModeSerializer
)
from renew_website.apps.api.deye.cloud_client import DeyeCloudClient, DeyeCloudError, WORK_MODE_MAP
from renew_website.apps.api.deye.manager import DeyeManager, DeyeManagerError
from .utils import run_work_mode_algorithm

logger = logging.getLogger(__name__)

# Global cache for websocket performance
_ws_performance_stats = {}

# -----------------------
# Views
# -----------------------

class InverterStatusView(APIView):
    """Get current status of all inverters."""
    permission_classes = [IsAuthenticated]
    serializer_class = InverterReadingSerializer
    
    def get(self, request):
        try:
            service = InverterDataService()
            data = service.get_current_generation_summary()
            serializer = DashboardDataSerializer(data=data)
            if serializer.is_valid():
                return Response(serializer.data)
            return Response(data)
        except Exception as e:
            logger.error(f"Failed to get inverter status: {e}")
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inverter_history(request, device_sn):
    """Get historical data for a specific inverter."""
    try:
        hours = int(request.query_params.get('hours', 24))
        service = InverterDataService()
        
        readings = service.get_inverter_history(device_sn, hours)
        
        data = {
            'device_sn': device_sn,
            'period_hours': hours,
            'readings': [
                {
                    'timestamp': r.timestamp.isoformat(),
                    'generation_power': r.generation_power,
                    'battery_soc': r.battery_soc,
                    'grid_power': r.grid_power,
                    'connect_status': r.connect_status
                }
                for r in readings
            ]
        }
        
        return Response(data)
    except Exception as e:
        logger.error(f"Failed to get inverter history: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    """
    Get EV charging recommendation based on real-time conditions (mocked 1 and 2 EV scenarios).
    """
    from django.utils import timezone
    from renew_website.apps.api.energy.models import InverterReading
    from renew_website.apps.api.weather.models import WeatherLog
    from renew_website.apps.algorithm.conditions import SystemState
    from renew_website.apps.algorithm.engine import DecisionEngine
    from renew_website.apps.algorithm.work_modes import SystemWorkMode

    try:
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        pv_power_kw = (latest_reading.generation_power or 0) / 1000.0 if latest_reading else 0.0
        battery_soc = float(latest_reading.battery_soc or 0) if latest_reading else 0.0
        station_data = latest_reading.station_data or {} if latest_reading else {}
        
        load_power_kw = station_data.get('load_power', 0) / 1000.0
        grid_voltage = station_data.get('grid_voltage', 230.0)
        is_grid_available = bool(grid_voltage > 190.0)

        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        cloud_cover = float(latest_weather.cloud_cover) if latest_weather else 0.0
        precipitation = float(latest_weather.precipitation_mm) if latest_weather else 0.0
        is_raining = precipitation > 0

        current_hour = timezone.localtime().hour
        is_night_tariff = (current_hour >= 22 or current_hour < 6)

        # Baseline common attributes
        base_kwargs = {
            'battery_soc': battery_soc,
            'is_grid_available': is_grid_available,
            'pv_production_kw': pv_power_kw,
            'building_load_kw': load_power_kw,
            'cloud_cover_percent': cloud_cover,
            'is_raining': is_raining,
            'weather_condition': 'clear',
            'is_night_tariff': is_night_tariff,
        }

        # Scenario 1: 1 EV (Demand = 11kW)
        state_1 = SystemState(
            active_ev_sessions=1,
            total_ev_demand_kw=11.0,
            **base_kwargs
        )
        decision_1 = DecisionEngine.evaluate(state_1)
        
        # Scenario 2: 2 EVs (Demand = 22kW)
        state_2 = SystemState(
            active_ev_sessions=2,
            total_ev_demand_kw=22.0,
            **base_kwargs
        )
        decision_2 = DecisionEngine.evaluate(state_2)

        def mode_to_str(m):
            if isinstance(m, SystemWorkMode):
                return m.name
            return str(m)

        def get_advice(power_allowed, target):
            if power_allowed >= target:
                return "Оптимално зареждане. Налична е достатъчно енергия."
            elif power_allowed > 0:
                return "Ограничено зареждане за предпазване на батерията."
            else:
                return "Липса на излишък. Зареждането ще бъде изчакване."

        info_context = (f"Текуща PV мощност: {pv_power_kw:.2f}kW, "
                        f"Консумация: {load_power_kw:.2f}kW, "
                        f"Батерия: {battery_soc:.1f}%")

        response_data = {
            "context": info_context,
            "scenario_1_ev": {
                "mode": mode_to_str(decision_1.get("mode")),
                "power_allowed": round(decision_1.get("ev_power_limit_kw", 0), 2),
                "advice": get_advice(decision_1.get("ev_power_limit_kw", 0), 11.0)
            },
            "scenario_2_ev": {
                "mode": mode_to_str(decision_2.get("mode")),
                "power_allowed": round(decision_2.get("ev_power_limit_kw", 0), 2),
                "advice": get_advice(decision_2.get("ev_power_limit_kw", 0), 22.0)
            }
        }
        
        return Response(response_data)
        
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Charging recommendation error: {e}\\n{traceback.format_exc()}")
        return Response(
            {"error": f"Грешка при генериране на препоръка: {e}"},
            status=500
        )
    except Exception as e:
        logger.error(f"Failed to get charging recommendation: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collect_data(request):
    """Manually trigger data collection from inverters."""
    try:
        service = InverterDataService()
        service.collect_current_data()
        
        return Response({
            "message": "Data collection completed",
            "timestamp": timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to collect data: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_data(request):
    """Get comprehensive dashboard data for monitoring."""
    try:
        service = InverterDataService()
        
        # Current generation summary
        current_data = service.get_current_generation_summary()
        
        # Recent readings
        recent_readings = service.get_latest_readings()

        # Get today's energy from Deye API directly (more accurate)
        data_source = 'unknown'
        try:
            # Use Manager to get normalized data from best source (Cloud or Local)
            manager = DeyeManager()
            
            # get_latest_data returns a dictionary serialized by DeyeCloudSerializer/DeyeLocalSerializer
            normalized_data = manager.get_latest_data()
            
            daily_energy = normalized_data.get('daily_energy', 0.0)
            total_energy = normalized_data.get('total_energy', 0.0)
            data_source = normalized_data.get('source', 'unknown')
            
            logger.debug(f"Energy stats from Manager ({data_source}): Daily={daily_energy}, Total={total_energy}")

        except (DeyeManagerError, Exception) as e:
            logger.warning(f"Failed to get energy from Deye Manager: {e}")
            # Fallback to database calculation using individual inverter readings
            today = timezone.now().date()
            today_readings = InverterReading.objects.filter(
                timestamp__date=today
            ).order_by('timestamp')
            
            # Calculate total energy today using individual inverter readings
            daily_energy = 0
            if len(today_readings) > 1:
                for i in range(1, len(today_readings)):
                    prev_power = today_readings[i-1].generation_power or 0  # Use individual generation_power
                    curr_power = today_readings[i].generation_power or 0    # Use individual generation_power
                    avg_power = (prev_power + curr_power) / 2
                    time_diff = (today_readings[i].timestamp - today_readings[i-1].timestamp).total_seconds() / 3600  # hours
                    daily_energy += (avg_power / 1000) * time_diff  # kWh
            
            total_energy = 0.0  # Would need historical data for this

        today = timezone.now().date()
        
        # Get all readings for today to calculate energy and peak
        today_readings = InverterReading.objects.filter(
            timestamp__date=today
        ).order_by('timestamp')
        
        # Calculate total energy today properly
        total_energy_today = 0
        if len(today_readings) > 1:
            for i in range(1, len(today_readings)):
                prev_power = today_readings[i-1].station_data.get('generationPower', 0) if today_readings[i-1].station_data else 0
                curr_power = today_readings[i].station_data.get('generationPower', 0) if today_readings[i].station_data else 0
                avg_power = (prev_power + curr_power) / 2
                time_diff = (today_readings[i].timestamp - today_readings[i-1].timestamp).total_seconds() / 3600  # hours
                total_energy_today += (avg_power / 1000) * time_diff  # kWh
        
        dashboard = {
            'connection_source': data_source,
            'current': current_data,
            'daily_stats': {
                'total_energy_kwh': round(total_energy_today, 2),
                'peak_generation_watts': max(
                    (r.station_data.get('generationPower', 0) if r.station_data else 0) for r in today_readings
                ) if today_readings else 0,
                'average_battery_soc': sum(
                    r.battery_soc or 0 for r in recent_readings
                ) / len(recent_readings) if recent_readings else 0
            },
            'recent_readings': [
                {
                    'device_sn': r.inverter.device_sn,
                    'generation_power': r.generation_power,
                    'battery_soc': r.battery_soc,
                    'timestamp': r.timestamp.isoformat()
                }
                for r in recent_readings[:5]
            ]
        }
        
        return Response(dashboard)
        
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


def energy_dashboard(request):
    return render(request, "deye/dashboard.html")

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def work_mode_config(request):
    """
    GET:
      returns config + deye_sync (deye is authoritative only if it returns a known mode)
    POST:
      - action=read_current_mode : best-effort cloud read; NEVER 400 due to unknown
      - otherwise: update local config + attempt Deye sync
    """
    if request.method == "GET":
        config = WorkMode.get_current_config()
        serializer = WorkModeSerializer(config)
        response_data = serializer.data

        manager = DeyeManager()
        deye_mode = manager.get_work_mode()
        
        if deye_mode and deye_mode.get("mode") in WORK_MODE_MAP:
            # Deye-known mode overrides local
            if config.mode != deye_mode["mode"]:
                config.mode = deye_mode["mode"]
                config.save(update_fields=["mode"])

            response_data["mode"] = deye_mode["mode"]
            response_data["deye_sync"] = {
                "current_mode": deye_mode["mode"],
                "device_sn": deye_mode.get("device_sn"),
                "last_sync": timezone.now().isoformat(),
                "authoritative": "deye_cloud" if deye_mode.get("source") == "cloud" else "local_inverter",
                "source": deye_mode.get("source", "unknown"),
            }
        else:
            response_data["deye_sync"] = {
                "current_mode": config.mode,
                "device_sn": deye_mode.get("device_sn") if deye_mode else None,
                "last_sync": timezone.now().isoformat(),
                "authoritative": "local_database",
                "source": deye_mode.get("source") if deye_mode else "deye_unavailable",
                "note": "Deye Cloud did not expose current mode (device/latest has no workMode) or Deye unavailable",
            }

        return Response(response_data)

    # POST
    try:
        manager = DeyeManager()

        if request.data.get("action") == "read_current_mode":
            deye_mode = manager.get_work_mode()
            config = WorkMode.get_current_config()

            # If Deye returns a known mode, align local DB. If unknown, keep DB as-is.
            if deye_mode and deye_mode.get("mode") in WORK_MODE_MAP:
                if config.mode != deye_mode["mode"]:
                    config.mode = deye_mode["mode"]
                    config.save(update_fields=["mode"])

            serializer = WorkModeSerializer(config)
            response_data = serializer.data
            response_data["deye_sync"] = {
                "current_mode": (deye_mode.get("mode") if deye_mode else "unknown"),
                "device_sn": (deye_mode.get("device_sn") if deye_mode else None),
                "last_sync": timezone.now().isoformat(),
                "authoritative": "deye_cloud" if (deye_mode and deye_mode.get("mode") in WORK_MODE_MAP) else "local_database",
                "source": (deye_mode.get("source") if deye_mode else "deye_unavailable"),
                "note": None if (deye_mode and deye_mode.get("mode") in WORK_MODE_MAP) else "Mode not available from cloud; showing local config",
            }
            return Response(response_data, status=200)

        # regular update configuration
        mode = request.data.get("mode", "selling_first")
        control_mode = request.data.get("control_mode", "manual")

        if mode not in WORK_MODE_MAP:
            return Response({"error": f"Invalid mode: {mode}"}, status=status.HTTP_400_BAD_REQUEST)
        if control_mode not in {"manual", "automatic"}:
            return Response({"error": f"Invalid control_mode: {control_mode}"}, status=status.HTTP_400_BAD_REQUEST)

        WorkMode.objects.all().update(is_active=False)

        config = WorkMode.objects.create(
            mode=mode,
            control_mode=control_mode,
            is_active=True,
        )

        sync_success = manager.set_work_mode(config.mode)

        if config.control_mode == "automatic":
            algorithm_selected = run_work_mode_algorithm()
            if algorithm_selected in WORK_MODE_MAP:
                config.algorithm_selected_mode = algorithm_selected
                config.save(update_fields=["algorithm_selected_mode"])
                
                # Try setting algorithm mode
                sync_success = manager.set_work_mode(algorithm_selected)

        serializer = WorkModeSerializer(config)
        response_data = serializer.data
        response_data["deye_sync"] = {
            "synced": bool(sync_success),
            "timestamp": timezone.now().isoformat(),
            "note": "Attempted to sync to Deye via Manager",
        }
        return Response(response_data, status=200)

    except Exception as e:
        logger.error("Failed to update work mode config: %s", e, exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def websocket_performance_stats(request):
    try:
        stats = []
        now = timezone.now()

        for station_id, perf_data in _ws_performance_stats.items():
            connection_start = perf_data.get("connection_start", now)
            duration = (now - connection_start).total_seconds()

            if duration > 0:
                send_rate = perf_data["bytes_sent"] / duration
                receive_rate = perf_data["bytes_received"] / duration
                total_rate = (perf_data["bytes_sent"] + perf_data["bytes_received"]) / duration
            else:
                send_rate = receive_rate = total_rate = 0

            last_activity = perf_data.get("last_activity", now)
            idle_time = (now - last_activity).total_seconds()

            stats.append(
                {
                    "station_id": station_id,
                    "connection_duration_seconds": round(duration, 2),
                    "messages_sent": perf_data["messages_sent"],
                    "messages_received": perf_data["messages_received"],
                    "bytes_sent": perf_data["bytes_sent"],
                    "bytes_received": perf_data["bytes_received"],
                    "total_bytes": perf_data["bytes_sent"] + perf_data["bytes_received"],
                    "send_rate_bps": round(send_rate, 2),
                    "receive_rate_bps": round(receive_rate, 2),
                    "total_rate_bps": round(total_rate, 2),
                    "idle_time_seconds": round(idle_time, 2),
                    "last_activity": last_activity.isoformat(),
                    "connection_start": connection_start.isoformat(),
                    "status": "active" if idle_time < 60 else "idle",
                }
            )

        stats.sort(key=lambda x: x["total_rate_bps"], reverse=True)

        return Response({"stations": stats, "total_stations": len(stats), "timestamp": now.isoformat()})

    except Exception as e:
        logger.error("Failed to get WebSocket performance stats: %s", e, exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def collect_energy_data(request):
    """
    Collect energy data from inverters and store in database.
    
    This endpoint is called by the frontend to manually trigger data collection.
    """
    try:
        # logger.debug("=== COLLECT ENERGY DATA CALLED ===")
        service = InverterDataService()
        
        # Collect current data from Deye Cloud and store in database
        # logger.debug("Starting data collection...")
        service.collect_current_data()
        # logger.debug("Data collection completed")
        
        # Get the collected data for response
        data = service.get_current_generation_summary()
        # logger.debug(f"Current generation summary: {data}")
        
        # logger.info(f"Energy data collected: {data}")
        
        return Response(
            {
                "success": True,
                "message": "Energy data collected successfully",
                "data": data,
                "timestamp": timezone.now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to collect energy data: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def run_algorithm(request):
    try:
        config = WorkMode.get_current_config()
        if config.control_mode != "automatic":
            return Response({"error": "Algorithm can only run in automatic mode"}, status=status.HTTP_400_BAD_REQUEST)

        algorithm_selected = run_work_mode_algorithm()
        if algorithm_selected not in WORK_MODE_MAP:
            return Response({"error": f"Algorithm returned invalid mode: {algorithm_selected}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        config.algorithm_selected_mode = algorithm_selected
        config.save(update_fields=["algorithm_selected_mode"])

        manager = DeyeManager()
        sync_success = manager.set_work_mode(algorithm_selected)

        return Response(
            {
                "message": "Algorithm executed successfully",
                "selected_mode": algorithm_selected,
                "selected_mode_display": config.get_algorithm_selected_mode_display(),
                "deye_sync": {"synced": bool(sync_success), "timestamp": timezone.now().isoformat()},
            }
        )

    except Exception as e:
        logger.error("Failed to run algorithm: %s", e, exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.http import HttpResponse
import csv
from datetime import timedelta

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def chart_data(request):
    """Return timeseries data for the dashboard charts."""
    try:
        # Default to last 24 hours
        time_range = request.GET.get('range', '24h')
        
        end_time = timezone.now()
        if time_range == '7d':
            start_time = end_time - timedelta(days=7)
        elif time_range == '30d':
            start_time = end_time - timedelta(days=30)
        else:
            start_time = end_time - timedelta(hours=24)
            
        readings = InverterReading.objects.filter(
            timestamp__gte=start_time,
            timestamp__lte=end_time
        ).order_by('timestamp')
        
        # We might have multiple inverters. Grouping by timestamp might be needed if they report separately.
        # But for simplicity, let's aggregate them by nearest minute or just return raw points if few.
        # If there are many inverters, we should sum their generation power at roughly same timestamps.
        
        # For now, let's return raw readings formatted for Chart.js
        labels = []
        pv_generation = []
        battery_soc = []
        grid_power = []
        building_load = []
        
        # To avoid massive duplicates, we can simply map them.
        for r in readings:
            labels.append(r.timestamp.strftime('%H:%M'))
            pv_generation.append((r.generation_power or 0) / 1000.0) # Convert to kW
            battery_soc.append(r.battery_soc or 0)
            
            # Use station_data for load if available
            load = r.station_data.get('load_power', 0) / 1000.0 if r.station_data else 0
            grid = (r.grid_power or 0) / 1000.0
            
            building_load.append(load)
            grid_power.append(grid)

        return Response({
            'labels': labels,
            'datasets': {
                'pv_generation': pv_generation,
                'battery_soc': battery_soc,
                'building_load': building_load,
                'grid_power': grid_power
            }
        })
    except Exception as e:
        logger.error(f"Error in chart_data: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_chart_csv(request):
    """Export chart data as CSV."""
    time_range = request.GET.get('range', '24h')
    
    end_time = timezone.now()
    if time_range == '7d':
        start_time = end_time - timedelta(days=7)
    elif time_range == '30d':
        start_time = end_time - timedelta(days=30)
    else:
        start_time = end_time - timedelta(hours=24)
        
    readings = InverterReading.objects.filter(
        timestamp__gte=start_time,
        timestamp__lte=end_time
    ).order_by('timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="energy_data_{time_range}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Inverter SN', 'PV Generation (kW)', 'Battery SOC (%)', 'Load Power (kW)', 'Grid Power (kW)'])

    for r in readings:
        load = r.station_data.get('load_power', 0) / 1000.0 if r.station_data else 0
        pv = (r.generation_power or 0) / 1000.0
        grid = (r.grid_power or 0) / 1000.0
        
        writer.writerow([
            r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            r.inverter.device_sn,
            f"{pv:.2f}",
            f"{r.battery_soc or 0:.1f}",
            f"{load:.2f}",
            f"{grid:.2f}"
        ])

    return response

@api_view(['POST'])
def start_charging_session(request):
    """
    Starts a simulated charging session in the chosen mode (Auto/Manual).
    This tells the background algorithm that a car is connected and charging should be managed dynamically.
    """
    from renew_website.apps.charging_stations.models import Transaction, Connector
    
    mode = request.data.get('mode', 'DYNAMIC_ECO_SOLAR_ONLY')
    
    # Just take the first available connector to simulate
    connector = Connector.objects.first()
    if not connector:
        return Response({'success': False, 'message': 'Няма налични зарядни конектори в системата.'})
        
    # Check if a session already exists for this connector
    active_txn = Transaction.objects.filter(connector=connector, stopped_at__isnull=True).first()
    if active_txn:
        return Response({'success': False, 'message': 'Вече има активна зарядна сесия на този конектор.'})
        
    # Create the new dynamic session (requested_power_kw=None means "Auto Mode" for algorithm)
    Transaction.objects.create(
        connector=connector,
        id_tag='SIMULATED_DASHBOARD_USER',
        requested_power_kw=None,
        status='active'
    )
    
    return Response({
        'success': True, 
        'message': f'Успешно стартирано зареждане в режим: {mode}. Алгоритъмът вече управлява мощността динамично.'
    })


# ==============================
# Energy Recommendations API
# ==============================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def direct_apply_inverter_mode(request):
    """Directly sends the recommended mode's Modbus commands to the inverter without needing a pending DB recommendation."""
    try:
        from renew_website.apps.api.deye.manager import DeyeManager
        from renew_website.apps.api.deye.control import get_modbus_commands_for_mode
        
        mode = request.data.get('mode')
        if not mode:
            return Response({'success': False, 'message': 'Missing mode parameter'}, status=400)
            
        modbus_commands = get_modbus_commands_for_mode(mode)
        
        if not modbus_commands:
            return Response({
                'success': True, 
                'message': f'Режимът {mode} не изисква промени по регистрите на инвертора.'
            })
            
        deye_mgr = DeyeManager()
        is_applied = deye_mgr.apply_modbus_commands(modbus_commands)
        
        if is_applied:
            return Response({'success': True, 'message': 'Командите бяха изпратени успешно по Modbus.'})
        else:
            return Response({'success': False, 'message': 'Комуникацията с Deye пропадна.'})
            
    except Exception as e:
        logger.error(f"Failed to directly apply inverter mode: {e}")
        return Response({'success': False, 'message': str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def energy_recommendations(request):
    """Get current energy recommendations from the algorithm."""
    try:
        # Get latest pending recommendation
        recommendation = EnergyRecommendation.get_latest_pending()
        
        if not recommendation:
            return Response({
                'has_recommendation': False,
                'message': 'Няма активни препоръки от алгоритъма'
            })
        
        # Calculate time until expiration
        time_until_expiry = (recommendation.expires_at - timezone.now()).total_seconds()
        
        response_data = {
            'has_recommendation': True,
            'recommendation': {
                'id': recommendation.id,
                'mode': recommendation.mode,
                'ev_power_limit_kw': recommendation.ev_power_limit_kw,
                'power_per_station_kw': recommendation.power_per_station_kw,
                'active_ev_sessions': recommendation.active_ev_sessions,
                'system_state': {
                    'battery_soc': recommendation.battery_soc,
                    'pv_production_kw': recommendation.pv_production_kw,
                    'building_load_kw': recommendation.building_load_kw,
                },
                'expires_in_seconds': int(time_until_expiry),
                'expires_at': recommendation.expires_at.isoformat(),
                'created_at': recommendation.created_at.isoformat(),
                'algorithm_data': recommendation.algorithm_data
            }
        }
        
        return Response(response_data)
        
    except Exception as e:
        logger.error(f"Failed to get energy recommendations: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_energy_recommendation(request, recommendation_id):
    """Apply a specific energy recommendation."""
    try:
        recommendation = EnergyRecommendation.objects.get(id=recommendation_id)
        
        if recommendation.status != 'pending':
            return Response({
                'success': False,
                'message': f'Препоръката вече е {recommendation.get_status_display()}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if recommendation has expired
        if timezone.now() > recommendation.expires_at:
            recommendation.status = 'expired'
            recommendation.save()
            return Response({
                'success': False,
                'message': 'Препоръката е изтекла'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Apply the recommendation
        success, message = recommendation.apply_recommendation()
        
        if success:
            return Response({
                'success': True,
                'message': message,
                'applied_at': recommendation.applied_at.isoformat()
            })
        else:
            return Response({
                'success': False,
                'message': message
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except EnergyRecommendation.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Препоръката не е намерена'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to apply energy recommendation: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ignore_energy_recommendation(request, recommendation_id):
    """Ignore a specific energy recommendation."""
    try:
        recommendation = EnergyRecommendation.objects.get(id=recommendation_id)
        
        if recommendation.status != 'pending':
            return Response({
                'success': False,
                'message': f'Препоръката вече е {recommendation.get_status_display()}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        recommendation.status = 'ignored'
        recommendation.save()
        
        return Response({
            'success': True,
            'message': 'Препоръката е игнорирана'
        })
            
    except EnergyRecommendation.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Препоръката не е намерена'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to ignore energy recommendation: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def energy_recommendations_history(request):
    """Get history of energy recommendations."""
    try:
        limit = int(request.query_params.get('limit', 20))
        recommendations = EnergyRecommendation.objects.all().order_by('-created_at')[:limit]
        
        history_data = []
        for rec in recommendations:
            history_data.append({
                'id': rec.id,
                'mode': rec.mode,
                'ev_power_limit_kw': rec.ev_power_limit_kw,
                'power_per_station_kw': rec.power_per_station_kw,
                'status': rec.status,
                'active_ev_sessions': rec.active_ev_sessions,
                'battery_soc': rec.battery_soc,
                'pv_production_kw': rec.pv_production_kw,
                'created_at': rec.created_at.isoformat(),
                'applied_at': rec.applied_at.isoformat() if rec.applied_at else None,
                'expires_at': rec.expires_at.isoformat()
            })
        
        return Response({
            'history': history_data,
            'total_count': EnergyRecommendation.objects.count()
        })
        
    except Exception as e:
        logger.error(f"Failed to get energy recommendations history: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
