from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.utils import timezone


LIVE_STATE_TIMEOUT = 60 * 60
LIVE_STATE_KEY_PREFIX = "charging_stations:live_state"


def _cache_key(station_id: int | str) -> str:
    return f"{LIVE_STATE_KEY_PREFIX}:{int(station_id)}"


def _humanize_requested_mode(requested_mode: Any) -> str:
    if requested_mode == "station-default":
        return "Station Default"
    if requested_mode in (None, "", "--"):
        return "--"
    return str(requested_mode).replace("-", " ").title()


def _normalize_status(status: Any) -> str | None:
    if status in (None, ""):
        return None
    normalized = str(status).strip().lower()
    if normalized == "offline":
        return "inactive"
    return normalized


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_active_session_signal(state: dict[str, Any]) -> bool:
    actual_power_kw = _as_float(state.get("actual_power_kw"))

    return (
        (actual_power_kw is not None and actual_power_kw > 0)
        or str(state.get("connector_status") or "").strip().lower() == "charging"
        or str(state.get("session_status_label") or "").strip().lower() == "active"
    )


def _mark_active_session(state: dict[str, Any]) -> None:
    state["status"] = "active"
    state["online"] = True
    state["connector_status"] = "charging"
    state["session_status_label"] = "Active"


def _default_state(station_id: int | str) -> dict[str, Any]:
    return {
        "station_id": int(station_id),
        "online": False,
        "status": "inactive",
        "connector_status": None,
        "vehicle_soc": None,
        "requested_power_kw": None,
        "requested_power_mode": None,
        "requested_power_display": "--",
        "requested_power_mode_label": "--",
        "actual_power_kw": None,
        "ems_limit_kw": None,
        "battery_capacity_kwh": None,
        "energy_kwh": None,
        "session_status_label": "No recent session",
        "last_event_ts": 0.0,
        "last_event_at": None,
    }


def get_station_live_state(station_id: int | str) -> dict[str, Any]:
    return cache.get(_cache_key(station_id)) or _default_state(station_id)


def get_station_live_states(station_ids: list[int] | tuple[int, ...]) -> dict[int, dict[str, Any]]:
    if not station_ids:
        return {}
    keys = {_cache_key(station_id): int(station_id) for station_id in station_ids}
    cached = cache.get_many(keys.keys())
    out: dict[int, dict[str, Any]] = {}
    for key, station_id in keys.items():
        out[station_id] = cached.get(key) or _default_state(station_id)
    return out


def get_latest_live_snapshot(station_states: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    ranked = [state for state in station_states.values() if state.get("last_event_ts")]
    if not ranked:
        return None
    return max(ranked, key=lambda state: float(state.get("last_event_ts") or 0.0))


def update_station_live_state_from_event(data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(data, dict) or "station_id" not in data:
        return None

    station_id = int(data["station_id"])
    current = get_station_live_state(station_id)
    event_type = str(data.get("type") or "")
    now = timezone.now()

    current["station_id"] = station_id
    current["last_event_ts"] = now.timestamp()
    current["last_event_at"] = data.get("timestamp") or now.isoformat()

    if event_type in {"station_status", "station_status_update", "status_update", "station_status_update"}:
        status = _normalize_status(data.get("status"))
        if status:
            current["status"] = status
            current["online"] = status not in {"inactive"}

    if event_type in {"connector_status_update", "connector_status"} or data.get("connector_status"):
        connector_status = str(data.get("connector_status") or data.get("status") or "").strip().lower() or None
        if connector_status:
            if connector_status in {"preparing", "finishing"} and _has_active_session_signal(current):
                connector_status = "charging"
            current["connector_status"] = connector_status
            if connector_status == "offline":
                current["status"] = "inactive"
                current["online"] = False
            elif connector_status in {"available", "preparing", "charging", "finishing", "faulted", "reserved", "suspendedev", "suspendedevse"}:
                current["status"] = "active"
                current["online"] = True
            if connector_status == "charging":
                current["session_status_label"] = "Active"
            elif connector_status == "preparing":
                current["session_status_label"] = "Preparing"
            elif connector_status == "finishing":
                current["session_status_label"] = "Finishing"
            elif connector_status in {"suspendedev", "suspendedevse"}:
                current["session_status_label"] = "Suspended"
            elif connector_status == "available":
                current["session_status_label"] = "Completed"
            elif connector_status == "offline":
                current["session_status_label"] = "Offline"

    if event_type == "soc_update" and data.get("soc_percentage") is not None:
        current["vehicle_soc"] = float(data["soc_percentage"])

    if event_type == "station_power_update":
        source = str(data.get("source") or "").strip().lower()
        current["requested_power_kw"] = data.get("requested_power_kw")
        current["requested_power_mode"] = data.get("requested_power_mode")
        current["requested_power_display"] = data.get("requested_power_display") or current.get("requested_power_display") or "--"
        current["requested_power_mode_label"] = _humanize_requested_mode(data.get("requested_power_mode"))
        current["actual_power_kw"] = data.get("actual_power_kw")
        current["ems_limit_kw"] = data.get("ems_limit_kw")
        current["battery_capacity_kwh"] = data.get("battery_capacity_kwh")
        current["energy_kwh"] = data.get("energy_kwh")

        if source == "stop_transaction":
            current["status"] = "active"
            current["online"] = True
            if current.get("connector_status") != "offline":
                current["connector_status"] = "available"
            current["session_status_label"] = "Completed"
        elif source == "start_transaction" or _has_active_session_signal(current):
            _mark_active_session(current)
        
        # Independent check: if power data arrives and connector is "preparing"/"finishing", upgrade to "charging"
        if current.get("connector_status") in {"preparing", "finishing"} and _has_active_session_signal(current):
            current["connector_status"] = "charging"
            current["session_status_label"] = "Active"

    if data.get("status") and event_type not in {"station_power_update", "soc_update"}:
        status = _normalize_status(data.get("status"))
        if status:
            current["status"] = status
            current["online"] = status not in {"inactive"}

    cache.set(_cache_key(station_id), current, timeout=LIVE_STATE_TIMEOUT)
    return current
