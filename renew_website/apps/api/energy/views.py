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
from .models import InverterReading
from .serializers import (
    InverterReadingSerializer, 
    DashboardDataSerializer,
    ChargingRecommendationRequestSerializer,
    ChargingRecommendationResponseSerializer
)

logger = logging.getLogger(__name__)


<<<<<<< Updated upstream
=======
# -----------------------
# Deye helpers
# -----------------------

def _extract_station_list(stations_payload: dict) -> list:
    """
    Your real /station/listWithDevice response shows stationList at root:
      {'code': '1000000', ..., 'stationList': [...]}
    Some wrappers put it under data:
      {'code':..., 'data': {'stationList': [...]}}
    Support both.
    """
    if not isinstance(stations_payload, dict):
        return []
    if isinstance(stations_payload.get("stationList"), list):
        return stations_payload.get("stationList") or []
    data = stations_payload.get("data") or {}
    if isinstance(data.get("stationList"), list):
        return data.get("stationList") or []
    return []


def get_master_inverter() -> dict | None:
    """
    Returns:
      {'device_sn': str, 'device_id': any, 'station_id': any}
    """
    try:
        client = DeyeCloudClient()
        
        # Use listWithDevice and filter deviceType=INVERTER (as per your client implementation).
        stations_payload = client.station_list_with_device(page=1, size=20, device_type="INVERTER")

        station_list = _extract_station_list(stations_payload)
        if not station_list:
            logger.warning("No stations returned from Deye Cloud")
            return None

        # Prefer a connected inverter; Deye response in your logs does not include isMaster.
        for st in station_list:
            station_id = st.get("id")
            devices = st.get("deviceListItems") or []
            
            # Pick first connected inverter
            for i, device in enumerate(devices):
                sn = device.get("deviceSn")
                cs = device.get("connectStatus")
                
                if device.get("deviceType") == "INVERTER" and cs == 1 and sn:
                    logger.debug("Using connected inverter as master: %s", sn)
                    return {
                        "device_sn": sn,
                        "device_id": device.get("deviceId"),
                        "station_id": station_id,
                    }

        # Fallback: first inverter regardless of connectStatus
        for st in station_list:
            station_id = st.get("id")
            devices = st.get("deviceListItems") or []
            for device in devices:
                sn = device.get("deviceSn")
                if device.get("deviceType") == "INVERTER" and sn:
                    logger.debug("Using fallback master inverter: %s", sn)
                    return {
                        "device_sn": sn,
                        "device_id": device.get("deviceId"),
                        "station_id": station_id,
                    }

        logger.warning("No inverter found in any station")
        return None

    except Exception as e:
        logger.error("Failed to get master inverter: %s", e, exc_info=True)
        return None


def sync_work_mode_to_deye(work_mode: str) -> bool:
    """
    Writes one of the 3 official modes to Deye:
      selling_first | zero_export_load | zero_export_ct
    """
    if work_mode not in WORK_MODE_MAP:
        logger.error("Invalid work mode for Deye sync: %s", work_mode)
        return False

    master = get_master_inverter()
    if not master:
        logger.warning("No master inverter found for work mode sync")
        return False

    try:
        client = DeyeCloudClient()
        order_status = client.set_work_mode(device_sn=master["device_sn"], mode=work_mode, poll_order=True)

        # Success criteria: not FAIL/FAILED/ERROR/REJECT..., TIMEOUT treated as "sent but not confirmed"
        if (order_status.status or "").upper() in {"FAIL", "FAILED", "ERROR", "REJECT", "REJECTED"}:
            logger.error(
                "Deye work mode sync failed: device=%s mode=%s order=%s status=%s",
                master["device_sn"], work_mode, order_status.order_id, order_status.status
            )
            return False

        logger.info(
            "Synced work mode %s to inverter %s (order=%s status=%s)",
            work_mode, master["device_sn"], order_status.order_id, order_status.status
        )
        return True

    except DeyeCloudError as e:
        logger.error("Deye Cloud API error syncing work mode: %s", e, exc_info=True)
        return False
    except Exception as e:
        logger.error("Failed to sync work mode to Deye Cloud: %s", e, exc_info=True)
        return False


def get_deye_work_mode() -> dict | None:
    """
    Best-effort read. In practice, Deye v1 often cannot expose the sys/workMode via device/latest.
    This must never throw 400 logic upstream.
    """
    master = get_master_inverter()
    if not master:
        logger.warning("No master inverter found to get work mode")
        return None

    try:
        client = DeyeCloudClient()

        # IMPORTANT: your client defines keyword-only arg: get_work_mode(self, *, device_sn: str)
        result = client.get_work_mode(device_sn=master["device_sn"])

        if result.get("mode") == "unknown":
            logger.info(
                "Work mode unknown for device %s (source=%s raw=%s)",
                master["device_sn"], result.get("source"), result.get("raw_mode")
            )
        return result

    except DeyeCloudError as e:
        logger.error("Deye Cloud API error getting work mode: %s", e, exc_info=True)
        return None
    except Exception as e:
        logger.error("Failed to get work mode from Deye Cloud: %s", e, exc_info=True)
        return None


# -----------------------
# Views
# -----------------------

>>>>>>> Stashed changes
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    """
    Get EV charging recommendation based on current conditions.
    
    Request body:
    {
        "vehicle_id": "vehicle_001",
        "target_soc": 80,
        "current_soc": 30,
        "max_power": 7200
    }
    """
    try:
        vehicle_id = request.data.get('vehicle_id')
        target_soc = int(request.data.get('target_soc'))
        current_soc = int(request.data.get('current_soc'))
        max_power = float(request.data.get('max_power'))
        
        if not all([vehicle_id, target_soc, current_soc, max_power]):
            return Response(
                {"error": "Missing required fields: vehicle_id, target_soc, current_soc, max_power"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        optimizer = EVChargingOptimizer()
        recommendation = optimizer.get_charging_recommendation(
            vehicle_id, target_soc, current_soc, max_power
        )
        
        return Response(recommendation)
        
    except (ValueError, TypeError) as e:
        return Response(
            {"error": f"Invalid data format: {e}"},
            status=status.HTTP_400_BAD_REQUEST
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
        
<<<<<<< Updated upstream
        # Calculate daily stats - use station data to avoid double counting
=======
        # Get today's energy from Deye API directly (more accurate)
        try:
            # station_latest API returns minimal data (mostly powers), not daily energy
            # To get DailyActiveProduction we need device_latest for the inverter(s)
            
            master = get_master_inverter()
            if master:
                device_data = service.client.get_device_latest(master["device_sn"])
                logger.debug(f"Device data for energy stats: {device_data}")
                
                daily_energy = 0.0
                total_energy = 0.0
                
                # Extract from device data
                # Structure: {'data': {'deviceList': [{'code':..., 'dataList': [...]}]}} OR {'code':..., 'deviceDataList': [...]}
                # The client.device_latest returns the raw response.
                
                data_list = []
                # Handle different response structures
                if isinstance(device_data, dict):
                    # Check for deviceDataList (common in some API versions)
                    if 'deviceDataList' in device_data:
                        first_dev = device_data['deviceDataList'][0] if device_data['deviceDataList'] else {}
                        data_list = first_dev.get('dataList', [])
                    # Check for data -> deviceList
                    elif 'data' in device_data and 'deviceList' in device_data['data']:
                        devs = device_data['data']['deviceList']
                        if devs:
                            data_list = devs[0].get('dataList', [])

                for item in data_list:
                    key = item.get('key')
                    if key == 'DailyActiveProduction':
                        daily_energy = float(item.get('value', 0))
                    elif key == 'TotalActiveProduction':
                        total_energy = float(item.get('value', 0))
                
                # logger.debug(f"Energy from Deye API (device {master['device_sn']}) - Daily: {daily_energy} kWh, Total: {total_energy} kWh")
            else:
                logger.warning("No master inverter found to fetch energy stats")
                daily_energy = 0.0
                total_energy = 0.0

        except Exception as e:
            logger.warning(f"Failed to get energy from Deye API: {e}")
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

        # Calculate peak generation from individual readings
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
    """Energy management dashboard page."""
    return render(request, 'deye/dashboard.html')
=======
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

        deye_mode = get_deye_work_mode()
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
                "authoritative": "deye_cloud",
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
        if request.data.get("action") == "read_current_mode":
            deye_mode = get_deye_work_mode()
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

        sync_success = sync_work_mode_to_deye(config.mode)

        if config.control_mode == "automatic":
            algorithm_selected = run_work_mode_algorithm()
            if algorithm_selected in WORK_MODE_MAP:
                config.algorithm_selected_mode = algorithm_selected
                config.save(update_fields=["algorithm_selected_mode"])
                sync_success = sync_work_mode_to_deye(algorithm_selected)

        serializer = WorkModeSerializer(config)
        response_data = serializer.data
        response_data["deye_sync"] = {
            "synced": bool(sync_success),
            "timestamp": timezone.now().isoformat(),
            "note": "Attempted to sync to Deye Cloud",
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

        sync_success = sync_work_mode_to_deye(algorithm_selected)

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
>>>>>>> Stashed changes
