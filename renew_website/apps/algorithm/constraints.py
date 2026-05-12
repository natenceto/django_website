from .conditions import ConstraintState, SystemState, get_safe_battery_discharge_limit, is_sun_reliable


class ConstraintEngine:
    """Computes what the EMS is currently allowed to do."""

    @classmethod
    def evaluate(cls, state: SystemState) -> ConstraintState:
        battery_decision = get_safe_battery_discharge_limit(state)
        site_available_import_kw = cls._get_site_available_import_kw(state)
        pv_priority_required = cls._requires_pv_priority(state)
        charging_paused = cls._should_pause_charging(state)
        grid_assist_allowed = cls._can_use_grid_assist(state, pv_priority_required, charging_paused, site_available_import_kw)
        grid_assist_limit_kw = site_available_import_kw if grid_assist_allowed else 0.0

        labels = []
        if not state.is_grid_available:
            labels.append("Grid Offline")
        if charging_paused:
            labels.append("Charging Paused")
        if battery_decision.protection_active:
            labels.append("Battery Protection")
        if not is_sun_reliable(state):
            labels.append("Cloud Protection")
        if pv_priority_required:
            labels.append("PV Priority")
        if state.is_night_tariff:
            labels.append("Night Tariff")
        if grid_assist_allowed:
            labels.append("Grid Assist")

        return ConstraintState(
            battery_discharge_allowed_kw=battery_decision.allowed_kw,
            grid_assist_allowed=grid_assist_allowed,
            grid_assist_limit_kw=grid_assist_limit_kw,
            pv_priority_required=pv_priority_required,
            emergency_reserve_active=not state.is_grid_available,
            charging_paused=charging_paused,
            site_available_import_kw=site_available_import_kw,
            battery_decision=battery_decision,
            labels=list(dict.fromkeys(labels)),
        )

    @staticmethod
    def _requires_pv_priority(state: SystemState) -> bool:
        if state.is_night_tariff:
            return False
        if state.battery_soc < 50.0:
            return True
        if state.weather_confidence > 0 and state.weather_solar_score < 0.55:
            return True
        if state.forecasted_pv_kw_30m is not None and state.forecasted_pv_kw_30m > state.pv_production_kw:
            return False
        return not is_sun_reliable(state)

    @staticmethod
    def _should_pause_charging(state: SystemState) -> bool:
        if not state.is_grid_available:
            return True
        if state.is_night_tariff and state.battery_soc < 50.0:
            return True
        if (
            state.active_ev_sessions == 0
            and state.pv_production_kw > 5.0
            and state.building_load_kw < 15.0
            and state.battery_soc < 98.0
        ):
            return True
        return False

    @staticmethod
    def _get_site_available_import_kw(state: SystemState) -> float:
        site_limit = state.site_max_import_kw or state.main_breaker_limit_kw or 0.0
        if site_limit <= 0:
            return 0.0
        return max(0.0, site_limit - state.building_load_kw)

    @staticmethod
    def _can_use_grid_assist(state: SystemState, pv_priority_required: bool, charging_paused: bool, site_available_import_kw: float) -> bool:
        if charging_paused or not state.is_grid_available or site_available_import_kw <= 0:
            return False
        return state.grid_policy_preference in {"limited", "assist", "fast_charge"} and not pv_priority_required