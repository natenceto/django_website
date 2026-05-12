"""Energy management utility functions."""
import logging

from django.utils import timezone

from renew_website.apps.algorithm.conditions import SystemState
from renew_website.apps.algorithm.engine import DecisionEngine
from renew_website.apps.algorithm.work_modes import SystemWorkMode

logger = logging.getLogger(__name__)


def _safe_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _classify_session_urgency(ev_soc):
    if ev_soc is None:
        return "unknown"
    if ev_soc < 30:
        return "critical"
    if ev_soc < 55:
        return "priority"
    if ev_soc < 80:
        return "normal"
    return "tapering"


def _urgency_weight(urgency):
    return {
        "critical": 4.0,
        "priority": 3.0,
        "normal": 2.0,
        "tapering": 1.0,
        "unknown": 2.0,
    }.get(urgency, 2.0)


def _build_active_ev_session_profiles():
    from renew_website.apps.charging_stations.models import Transaction

    active_transactions = (
        Transaction.objects.filter(status="active", stopped_at__isnull=True)
        .select_related("connector__station")
        .prefetch_related("meter_values")
        .order_by("started_at")
    )

    sessions = []
    for transaction in active_transactions:
        latest_meter = transaction.meter_values.order_by("-timestamp").first()
        connector = transaction.connector
        current_power_kw = _safe_float(getattr(connector, "current_power_kw", None))
        if current_power_kw <= 0 and latest_meter and latest_meter.power_w is not None:
            current_power_kw = _safe_float(latest_meter.power_w) / 1000.0

        requested_power_kw = _safe_float(transaction.requested_power_kw)
        if requested_power_kw <= 0:
            requested_power_kw = _safe_float(getattr(connector, "max_power_kw", None), 11.0)

        ev_soc = None
        if latest_meter and latest_meter.soc_percentage is not None:
            ev_soc = _safe_float(latest_meter.soc_percentage)

        target_soc = 80.0 if ev_soc is not None and ev_soc < 80.0 else 100.0
        remaining_soc = max(target_soc - ev_soc, 0.0) if ev_soc is not None else None
        assumed_battery_capacity_kwh = 60.0
        eta_hours = None
        if remaining_soc is not None and requested_power_kw > 0:
            eta_hours = round(((remaining_soc / 100.0) * assumed_battery_capacity_kwh) / requested_power_kw, 2)

        sessions.append({
            "transaction_id": transaction.id,
            "station_id": connector.station_id,
            "station_label": connector.station.formatted_serial() if connector.station_id else f"Station {connector.station_id}",
            "connector_id": connector.connector_id,
            "current_power_kw": round(current_power_kw, 2),
            "requested_power_kw": round(requested_power_kw, 2),
            "max_power_kw": round(_safe_float(getattr(connector, "max_power_kw", None), requested_power_kw), 2),
            "ev_soc": round(ev_soc, 1) if ev_soc is not None else None,
            "urgency": _classify_session_urgency(ev_soc),
            "eta_hours": eta_hours,
        })

    return sessions


def _allocate_power_to_sessions(session_profiles, total_limit_kw):
    if not session_profiles or total_limit_kw <= 0:
        return []

    remaining = float(total_limit_kw)
    total_weight = sum(_urgency_weight(session["urgency"]) for session in session_profiles) or 1.0
    allocations = []

    for index, session in enumerate(session_profiles):
        if remaining <= 0:
            allocation = 0.0
        elif index == len(session_profiles) - 1:
            allocation = min(remaining, session["requested_power_kw"])
        else:
            allocation = min(
                session["requested_power_kw"],
                round(total_limit_kw * (_urgency_weight(session["urgency"]) / total_weight), 2),
            )
        remaining = max(0.0, round(remaining - allocation, 2))
        allocations.append({
            "transaction_id": session["transaction_id"],
            "station_label": session["station_label"],
            "connector_id": session["connector_id"],
            "urgency": session["urgency"],
            "ev_soc": session["ev_soc"],
            "allocated_power_kw": round(allocation, 2),
            "requested_power_kw": session["requested_power_kw"],
            "eta_hours": session["eta_hours"],
        })

    return allocations


def evaluate_current_energy_strategy():
    from renew_website.apps.api.energy.models import InverterReading
    from renew_website.apps.api.weather.models import WeatherLog

    latest_reading = InverterReading.objects.order_by("-timestamp").first()
    latest_weather = WeatherLog.objects.order_by("-timestamp").first()
    session_profiles = _build_active_ev_session_profiles()

    station_data = latest_reading.station_data or {} if latest_reading else {}
    pv_power_kw = _safe_float(getattr(latest_reading, "generation_power", 0)) / 1000.0 if latest_reading else 0.0
    battery_soc = _safe_float(getattr(latest_reading, "battery_soc", 0)) if latest_reading else 0.0
    building_load_kw = _safe_float(station_data.get("load_power", station_data.get("loadPower", 0))) / 1000.0
    grid_voltage = _safe_float(station_data.get("grid_voltage", 230.0), 230.0)
    is_grid_available = grid_voltage > 190.0

    cloud_cover = _safe_float(getattr(latest_weather, "cloud_cover", 0.0)) if latest_weather else 0.0
    precipitation = _safe_float(getattr(latest_weather, "precipitation_mm", 0.0)) if latest_weather else 0.0
    is_raining = precipitation > 0
    weather_label = getattr(latest_weather, "condition", None) or ("rain" if is_raining else "clear")

    now = timezone.now()
    current_hour = timezone.localtime(now).hour if timezone.is_aware(now) else now.hour
    is_night_tariff = current_hour >= 22 or current_hour < 6

    active_ev_sessions = len(session_profiles)
    total_ev_demand_kw = round(sum(session["requested_power_kw"] for session in session_profiles), 2)
    current_ev_power_kw = round(sum(session["current_power_kw"] for session in session_profiles), 2)
    urgent_sessions = [session for session in session_profiles if session["urgency"] == "critical"]
    high_priority_sessions = [session for session in session_profiles if session["urgency"] in {"critical", "priority"}]

    state = SystemState(
        battery_soc=battery_soc,
        is_grid_available=is_grid_available,
        pv_production_kw=pv_power_kw,
        building_load_kw=building_load_kw,
        active_ev_sessions=active_ev_sessions,
        total_ev_demand_kw=total_ev_demand_kw,
        cloud_cover_percent=cloud_cover,
        is_raining=is_raining,
        weather_condition=weather_label,
        is_night_tariff=is_night_tariff,
    )
    decision = DecisionEngine.evaluate(state)
    mode = str(decision.get("mode"))
    ev_power_limit_kw = _safe_float(decision.get("ev_power_limit_kw"))

    if active_ev_sessions:
        if urgent_sessions and is_grid_available and not is_night_tariff:
            mode = str(SystemWorkMode.FAST_CHARGE_GRID)
            ev_power_limit_kw = max(ev_power_limit_kw, total_ev_demand_kw or (len(urgent_sessions) * 11.0))
        elif high_priority_sessions and battery_soc >= 60 and not is_raining:
            mode = str(SystemWorkMode.DYNAMIC_MAX_RENEWABLE)
            ev_power_limit_kw = max(ev_power_limit_kw, min(total_ev_demand_kw, pv_power_kw + 5.0))
        elif session_profiles and all(session["urgency"] == "tapering" for session in session_profiles if session["ev_soc"] is not None) and battery_soc < 75:
            mode = str(SystemWorkMode.CHARGE_BATTERY)
            ev_power_limit_kw = min(ev_power_limit_kw, max(0.0, pv_power_kw - building_load_kw))

    session_allocations = _allocate_power_to_sessions(session_profiles, ev_power_limit_kw)

    return {
        "mode": mode,
        "decision": decision,
        "ev_power_limit_kw": round(ev_power_limit_kw, 2),
        "state": state,
        "timestamp": latest_reading.timestamp if latest_reading else now,
        "weather_label": weather_label,
        "cloud_cover_percent": round(cloud_cover, 1),
        "precipitation_mm": round(precipitation, 2),
        "battery_soc": round(battery_soc, 1),
        "pv_power_kw": round(pv_power_kw, 2),
        "building_load_kw": round(building_load_kw, 2),
        "grid_available": is_grid_available,
        "active_ev_sessions": active_ev_sessions,
        "current_ev_power_kw": round(current_ev_power_kw, 2),
        "total_ev_demand_kw": round(total_ev_demand_kw, 2),
        "active_station_count": len({session["station_id"] for session in session_profiles}),
        "urgent_session_count": len(urgent_sessions),
        "session_profiles": session_profiles,
        "session_allocations": session_allocations,
        "is_night_tariff": is_night_tariff,
    }


def run_work_mode_algorithm(inverter=None):
    """Return the current platform strategy mode selected by the algorithm."""
    return evaluate_current_energy_strategy()["mode"]
