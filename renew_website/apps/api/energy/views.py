"""
Energy management API views for EV charging optimization.
"""
import logging
from django.conf import settings
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
    ChartDataResponseSerializer,
    ChargingRecommendationSummarySerializer,
    CurrentGenerationSummarySerializer,
    EMSApplyResponseSerializer,
    EnergyDashboardSerializer,
    EnergyRecommendationsResponseSerializer,
    ErrorResponseSerializer,
    GenericStatusResponseSerializer,
    InverterHistoryResponseSerializer,
    InverterReadingSerializer,
    MessageTimestampSerializer,
    RecommendationActionResponseSerializer,
    RecommendationHistoryResponseSerializer,
    WorkModeSerializer,
)
from renew_website.apps.api.deye.cloud_client import DeyeCloudClient, DeyeCloudError, WORK_MODE_MAP
from renew_website.apps.api.deye.manager import DeyeManager, DeyeManagerError
from renew_website.apps.api.deye.serializers import DeyeCloudSerializer
from renew_website.apps.api.schema import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
from renew_website.apps.charging_stations.models import MeterValue, Transaction
from .decision_service import EnergyOrchestrator
from .execution_service import EMSExecutionService
from .utils import run_work_mode_algorithm

logger = logging.getLogger(__name__)

STRATEGY_LABELS_EN = {
    'DYNAMIC_ECO_SOLAR_ONLY': 'Dynamic: Solar Only (Battery Protection)',
    'DYNAMIC_MAX_RENEWABLE': 'Dynamic: Fast Eco (Solar + Battery)',
    'FAST_CHARGE_GRID': 'Blended: Fast Charging with Grid',
    'PROTECT_BATTERY': 'Battery Protection (Night Tariff)',
    'CHARGE_BATTERY': 'Battery Priority Charging',
    'EMERGENCY_BACKUP': 'Emergency Island Mode',
}


def _integrate_energy_kwh(readings):
    total_energy = 0.0
    if len(readings) <= 1:
        return total_energy

    for index in range(1, len(readings)):
        previous_reading = readings[index - 1]
        current_reading = readings[index]
        previous_power = previous_reading.station_data.get('generationPower', 0) if previous_reading.station_data else 0
        current_power = current_reading.station_data.get('generationPower', 0) if current_reading.station_data else 0
        average_power = (previous_power + current_power) / 2
        time_diff_hours = (current_reading.timestamp - previous_reading.timestamp).total_seconds() / 3600
        total_energy += (average_power / 1000) * time_diff_hours

    return round(total_energy, 2)

# Global cache for websocket performance
_ws_performance_stats = {}


def _strategy_to_str(strategy):
    return strategy.name if hasattr(strategy, 'name') else str(strategy)


def _strategy_to_label(strategy):
    strategy_key = _strategy_to_str(strategy)
    return STRATEGY_LABELS_EN.get(strategy_key, strategy_key.replace('_', ' ').title())


def _serialize_strategy_decision(state, decision, target_ev_sessions, target_ev_demand_kw):
    strategy = decision.strategy
    plan = decision.allocation_plan
    return {
        'strategy': _strategy_to_str(strategy),
        'strategy_label': _strategy_to_label(strategy),
        'active_ev_sessions': target_ev_sessions,
        'requested_ev_demand_kw': round(target_ev_demand_kw, 2),
        'ev_power_limit_kw': round(float(plan.get('ev_charge_limit_kw', 0.0) or 0.0), 2),
        'allocation_plan': plan,
        'current_snapshot': {
            'battery_soc': state.battery_soc,
            'pv_power_kw': state.pv_production_kw,
            'load_power_kw': state.building_load_kw,
            'weather_condition': state.weather_condition,
            'cloud_cover_percent': state.cloud_cover_percent,
            'weather_solar_score': state.weather_solar_score,
            'weather_risk_score': state.weather_risk_score,
            'is_night_tariff': state.is_night_tariff,
            'active_ev_sessions': state.active_ev_sessions,
            'total_ev_demand_kw': state.total_ev_demand_kw,
        },
    }

# -----------------------
# Views
# -----------------------

class InverterStatusView(APIView):
    """Get current status of all inverters."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CurrentGenerationSummarySerializer, 503: ErrorResponseSerializer})
    
    def get(self, request):
        try:
            service = InverterDataService()
            data = service.get_current_generation_summary()
            serializer = CurrentGenerationSummarySerializer(data=data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Failed to get inverter status: {e}")
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


@extend_schema(
    parameters=[
        OpenApiParameter(name='device_sn', type=OpenApiTypes.STR, location=OpenApiParameter.PATH),
        OpenApiParameter(name='hours', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False),
    ],
    responses={200: InverterHistoryResponseSerializer, 503: ErrorResponseSerializer},
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
        
        serializer = InverterHistoryResponseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Failed to get inverter history: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@extend_schema(responses={200: ChargingRecommendationSummarySerializer, 500: ErrorResponseSerializer})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    """
    Get EV charging recommendation based on real-time conditions (mocked 1 and 2 EV scenarios).
    """
    try:
        orchestrator = EnergyOrchestrator()
        current_decision = orchestrator.evaluate_current_decision()
        decision_1 = orchestrator.evaluate_capacity_scenario(1, 11.0)
        decision_2 = orchestrator.evaluate_capacity_scenario(2, 22.0)
        current_state = current_decision.state or decision_1.state

        snapshot = {
            'pv_power_kw': round(current_state.pv_production_kw, 2) if current_state else 0.0,
            'building_load_kw': round(current_state.building_load_kw, 2) if current_state else 0.0,
            'battery_soc': round(current_state.battery_soc, 1) if current_state else 0.0,
        }

        def get_advice(power_allowed, target):
            if power_allowed >= target:
                return "Optimal charging. Sufficient energy is available."
            elif power_allowed > 0:
                return "Charging is limited to protect the battery reserve."
            else:
                return "No surplus energy is available. Charging should wait."

        info_context = (
            f"Current PV power: {snapshot['pv_power_kw']:.2f} kW, "
            f"Building load: {snapshot['building_load_kw']:.2f} kW, "
            f"Battery SOC: {snapshot['battery_soc']:.1f}%"
        )

        response_data = {
            "context": info_context,
            "scenario_1_ev": {
                "strategy": _strategy_to_label(decision_1.strategy),
                "power_allowed": round(decision_1.allocation_plan.get("ev_charge_limit_kw", 0), 2),
                "advice": get_advice(decision_1.allocation_plan.get("ev_charge_limit_kw", 0), 11.0),
                "allocation_plan": decision_1.allocation_plan,
            },
            "scenario_2_ev": {
                "strategy": _strategy_to_label(decision_2.strategy),
                "power_allowed": round(decision_2.allocation_plan.get("ev_charge_limit_kw", 0), 2),
                "advice": get_advice(decision_2.allocation_plan.get("ev_charge_limit_kw", 0), 22.0),
                "allocation_plan": decision_2.allocation_plan,
            },
            "recommended_plan": _serialize_strategy_decision(
                current_decision.state,
                current_decision,
                current_decision.state.active_ev_sessions if current_decision.state else 0,
                current_decision.state.total_ev_demand_kw if current_decision.state else 0.0,
            ),
        }
        
        serializer = ChargingRecommendationSummarySerializer(data=response_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error("Charging recommendation error: %s", e, exc_info=True)
        return Response(
            {"error": f"Грешка при генериране на препоръка: {e}"},
            status=500
        )


@extend_schema(request=None, responses={200: MessageTimestampSerializer, 503: ErrorResponseSerializer})
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collect_data(request):
    """Manually trigger data collection from inverters."""
    try:
        service = InverterDataService()
        service.collect_current_data()
        
        response_payload = {
            "message": "Data collection completed",
            "timestamp": timezone.now().isoformat()
        }
        serializer = MessageTimestampSerializer(data=response_payload)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Failed to collect data: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@extend_schema(responses={200: EnergyDashboardSerializer, 503: ErrorResponseSerializer})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_data(request):
    """Get comprehensive dashboard data for monitoring."""
    try:
        service = InverterDataService()

        active_transactions = list(
            Transaction.objects.filter(stopped_at__isnull=True)
            .select_related('connector', 'connector__station')
            .order_by('-started_at')
        )

        latest_meter_values = {
            meter_value.transaction_id: meter_value.power_w
            for meter_value in MeterValue.objects.filter(
                transaction_id__in=[transaction.id for transaction in active_transactions]
            )
            .order_by('transaction_id', '-timestamp')
            .distinct('transaction_id')
        } if active_transactions else {}

        ev_power_watts = 0.0
        for transaction in active_transactions:
            latest_power_w = latest_meter_values.get(transaction.id)
            if latest_power_w is not None:
                ev_power_watts += float(latest_power_w or 0)
            elif transaction.requested_power_kw is not None:
                ev_power_watts += float(transaction.requested_power_kw or 0) * 1000.0
        
        # Current generation summary
        current_data = service.get_current_generation_summary()
        
        # Recent readings
        recent_readings = service.get_latest_readings()

        # Get normalized energy stats from the best available Deye source.
        data_source = 'unknown'
        normalized_data = None
        daily_energy = 0.0
        monthly_energy = 0.0
        total_energy = 0.0
        installed_capacity = float(getattr(settings, 'DEYE_INSTALLED_CAPACITY_KWP', 10.0) or 10.0)
        try:
            # Use Manager to get normalized data from best source (Cloud or Local)
            manager = DeyeManager()
            active_inverter = manager.get_active_inverter() or {}
            
            # get_latest_data returns a dictionary serialized by DeyeCloudSerializer/DeyeLocalSerializer
            normalized_data = manager.get_latest_data()
            
            daily_energy = normalized_data.get('daily_energy', 0.0)
            monthly_energy = normalized_data.get('monthly_energy', 0.0)
            total_energy = normalized_data.get('total_energy', 0.0)
            installed_capacity = float(normalized_data.get('capacity') or installed_capacity)
            data_source = normalized_data.get('source', 'unknown')
            
            logger.debug(
                f"Energy stats from Manager ({data_source}): Daily={daily_energy}, Monthly={monthly_energy}, Total={total_energy}"
            )

            if data_source == 'cloud':
                target_sn = active_inverter.get('device_sn')
                station_candidates = manager.cloud.get_station_list(page=1, size=20)
                station_match = None
                for station in station_candidates:
                    devices = station.get('deviceListItems') or []
                    if any(str(device.get('deviceSn')) == str(target_sn) for device in devices):
                        station_match = station
                        break
                if not station_match and station_candidates:
                    station_match = station_candidates[0]

                station_id = (station_match or {}).get('id') or (station_match or {}).get('stationId')
                if station_id:
                    station_latest = manager.cloud.station_latest(int(station_id))
                    current_generation = station_latest.get('generationPower')
                    current_battery_soc = station_latest.get('batterySOC')
                    current_building_load = station_latest.get('consumptionPower')
                    current_grid_input = station_latest.get('wirePower')
                    if current_grid_input is None:
                        current_grid_input = station_latest.get('purchasePower')
                    if current_grid_input is None:
                        current_grid_input = station_latest.get('gridPower')
                    current_battery_power = station_latest.get('batteryPower')
                    if current_generation is not None:
                        normalized_data['generation_power'] = float(current_generation)
                    if current_battery_soc is not None:
                        normalized_data['battery_soc'] = float(current_battery_soc)
                    if current_building_load is not None:
                        normalized_data['load_power'] = float(current_building_load)
                    if current_grid_input is not None:
                        normalized_data['grid_power'] = float(current_grid_input)
                    if current_battery_power is not None:
                        normalized_data['battery_power'] = float(current_battery_power)

                inverter_sns = [
                    device.get('deviceSn')
                    for device in (station_match or {}).get('deviceListItems', [])
                    if device.get('deviceType') == 'INVERTER' and device.get('deviceSn')
                ]
                if inverter_sns:
                    device_latest = manager.cloud.get_device_latest(inverter_sns)
                    device_items = device_latest.get('deviceDataList') or (device_latest.get('data') or {}).get('deviceDataList') or []
                    aggregated_daily_energy = 0.0
                    aggregated_monthly_energy = 0.0
                    aggregated_total_energy = 0.0

                    for item in device_items:
                        serialized_item = dict(item)
                        serialized_item['device_sn'] = serialized_item.get('deviceSn')
                        serialized_item['source'] = 'cloud'
                        normalized_item = DeyeCloudSerializer(instance=serialized_item).data
                        aggregated_daily_energy += float(normalized_item.get('daily_energy') or 0.0)
                        aggregated_monthly_energy += float(normalized_item.get('monthly_energy') or 0.0)
                        aggregated_total_energy += float(normalized_item.get('total_energy') or 0.0)

                    if aggregated_daily_energy:
                        daily_energy = aggregated_daily_energy
                    if aggregated_monthly_energy:
                        monthly_energy = aggregated_monthly_energy
                    if aggregated_total_energy:
                        total_energy = aggregated_total_energy

        except (DeyeManagerError, Exception) as e:
            logger.warning(f"Failed to get energy from Deye Manager: {e}")
            data_source = 'database'

        if normalized_data:
            current_data['total_generation_watts'] = round(float(normalized_data.get('generation_power') or 0), 2)
            current_data['average_battery_soc'] = round(float(normalized_data.get('battery_soc') or 0), 2)
            current_data['grid_power_watts'] = round(float(normalized_data.get('grid_power') or 0), 2)
            current_data['load_power_watts'] = round(float(normalized_data.get('load_power') or 0), 2)
            current_data['battery_power_watts'] = round(float(normalized_data.get('battery_power') or 0), 2)

        current_data['ev_power_watts'] = round(ev_power_watts, 2)
        current_data['active_ev_sessions'] = len(active_transactions)

        today = timezone.now().date()
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Get all readings for today to calculate energy and peak
        today_readings = InverterReading.objects.filter(
            timestamp__date=today
        ).order_by('timestamp')
        month_readings = InverterReading.objects.filter(
            timestamp__gte=month_start
        ).order_by('timestamp')
        
        total_energy_today = _integrate_energy_kwh(today_readings)
        total_energy_month = _integrate_energy_kwh(month_readings)

        if not daily_energy:
            daily_energy = total_energy_today
        if not monthly_energy:
            monthly_energy = total_energy_month
        
        dashboard = {
            'connection_source': data_source,
            'current': current_data,
            'production_summary': {
                'current_power_watts': round(float(current_data.get('total_generation_watts') or 0), 0),
                'installed_capacity_kwp': round(float(installed_capacity or 0), 2),
                'daily_energy_kwh': round(float(daily_energy or 0), 2),
                'monthly_energy_kwh': round(float(monthly_energy or 0), 2),
                'total_energy_kwh': round(float(total_energy or 0), 2),
                'source': data_source,
            },
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
        
        serializer = EnergyDashboardSerializer(data=dashboard)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
        
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

        algorithm_result = EnergyOrchestrator().evaluate_current_decision()
        algorithm_selected = algorithm_result.strategy
        allocation_plan = algorithm_result.allocation_plan
        if not algorithm_selected:
            return Response({"error": "Algorithm could not determine an EMS strategy"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        config.algorithm_selected_mode = _strategy_to_str(algorithm_selected)
        config.save(update_fields=["algorithm_selected_mode"])

        return Response(
            {
                "message": "EMS strategy computed successfully",
                "selected_mode": _strategy_to_str(algorithm_selected),
                "selected_mode_display": config.get_algorithm_selected_mode_display(),
                "allocation_plan": allocation_plan,
                "deye_sync": {
                    "synced": False,
                    "timestamp": timezone.now().isoformat(),
                    "note": "Strategy computed only. Apply sends charger limits without changing inverter operating mode.",
                },
            }
        )

    except Exception as e:
        logger.error("Failed to run algorithm: %s", e, exc_info=True)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.http import HttpResponse
import csv
from datetime import timedelta

@extend_schema(
    parameters=[OpenApiParameter(name='range', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False)],
    responses={200: ChartDataResponseSerializer, 500: ErrorResponseSerializer},
)
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

        response_payload = {
            'labels': labels,
            'datasets': {
                'pv_generation': pv_generation,
                'battery_soc': battery_soc,
                'building_load': building_load,
                'grid_power': grid_power
            }
        }
        serializer = ChartDataResponseSerializer(data=response_payload)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Error in chart_data: {e}")
        return Response({"error": str(e)}, status=500)

@extend_schema(
    parameters=[OpenApiParameter(name='range', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False)],
    responses={200: OpenApiResponse(response=OpenApiTypes.BINARY, description='CSV export')},
)
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

@extend_schema(request=OpenApiTypes.OBJECT, responses={200: EMSApplyResponseSerializer, 400: GenericStatusResponseSerializer, 500: GenericStatusResponseSerializer})
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def direct_apply_inverter_mode(request):
    """Apply an EMS allocation plan without changing the fixed inverter operating policy."""
    try:
        allocation_plan = request.data.get('allocation_plan') or {}
        if not allocation_plan:
            mode = request.data.get('mode')
            if mode:
                algorithm_result = run_work_mode_algorithm()
                allocation_plan = algorithm_result.get('allocation_plan', {})

        if not allocation_plan:
            return Response({'success': False, 'message': 'Missing allocation_plan payload'}, status=400)

        result = EMSExecutionService().apply_allocation_plan(allocation_plan)
        return Response(result.to_dict())
            
    except Exception as e:
        logger.error(f"Failed to directly apply EMS allocation: {e}")
        return Response({'success': False, 'message': str(e)}, status=500)

@extend_schema(responses={200: EnergyRecommendationsResponseSerializer, 500: ErrorResponseSerializer})
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
        
        serializer = EnergyRecommendationsResponseSerializer(data=response_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Failed to get energy recommendations: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(request=None, responses={200: RecommendationActionResponseSerializer, 400: RecommendationActionResponseSerializer, 404: RecommendationActionResponseSerializer, 500: ErrorResponseSerializer})
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


@extend_schema(request=None, responses={200: RecommendationActionResponseSerializer, 400: RecommendationActionResponseSerializer, 404: RecommendationActionResponseSerializer, 500: ErrorResponseSerializer})
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


@extend_schema(
    parameters=[OpenApiParameter(name='limit', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, required=False)],
    responses={200: RecommendationHistoryResponseSerializer, 500: ErrorResponseSerializer},
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
        
        response_payload = {
            'history': history_data,
            'total_count': EnergyRecommendation.objects.count()
        }
        serializer = RecommendationHistoryResponseSerializer(data=response_payload)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)
        
    except Exception as e:
        logger.error(f"Failed to get energy recommendations history: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
