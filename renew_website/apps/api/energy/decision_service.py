from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from renew_website.apps.charging_stations.models import Transaction

from .services import InverterDataService


@dataclass(slots=True)
class EnergyState:
    battery_soc: float
    pv_production_kw: float
    building_load_kw: float
    weather_condition: str | None
    cloud_cover_percent: float | None
    weather_solar_score: float | None
    weather_risk_score: float | None
    is_night_tariff: bool
    active_ev_sessions: int
    total_ev_demand_kw: float


@dataclass(slots=True)
class EnergyDecision:
    strategy: str
    allocation_plan: dict
    state: EnergyState


class EnergyOrchestrator:
    """Lightweight energy decision service used by the energy API views."""

    def __init__(self):
        self.inverter_service = InverterDataService()

    def _build_state(self) -> EnergyState:
        summary = self.inverter_service.get_current_generation_summary()
        readings = summary.get('readings') or []
        station_data = {}
        if readings:
            # Current generation summary is derived from the latest reading set.
            latest_readings = self.inverter_service.get_latest_readings()
            if latest_readings:
                station_data = latest_readings[0].station_data or {}

        active_transactions = list(
            Transaction.objects.filter(status='active').select_related('connector__station')
        )
        total_ev_demand_kw = 0.0
        for transaction in active_transactions:
            if transaction.requested_power_kw is not None:
                total_ev_demand_kw += float(transaction.requested_power_kw)
            else:
                total_ev_demand_kw += float(transaction.connector.station.power_output or 0)

        now = timezone.localtime()
        return EnergyState(
            battery_soc=float(summary.get('average_battery_soc') or 0.0),
            pv_production_kw=round(float(summary.get('total_generation_watts') or 0.0) / 1000.0, 2),
            building_load_kw=round(float(station_data.get('consumptionPower') or station_data.get('load_power') or 0.0) / 1000.0, 2),
            weather_condition=None,
            cloud_cover_percent=None,
            weather_solar_score=None,
            weather_risk_score=None,
            is_night_tariff=bool(now.hour < 7 or now.hour >= 22),
            active_ev_sessions=len(active_transactions),
            total_ev_demand_kw=round(total_ev_demand_kw, 2),
        )

    def _decide_strategy(self, state: EnergyState, target_ev_sessions: int, target_ev_demand_kw: float) -> EnergyDecision:
        available_solar_kw = max(state.pv_production_kw - state.building_load_kw, 0.0)
        battery_support_kw = 0.0
        if state.battery_soc >= 80:
            battery_support_kw = 11.0
        elif state.battery_soc >= 60:
            battery_support_kw = 5.5

        total_available_kw = round(available_solar_kw + battery_support_kw, 2)

        if total_available_kw >= target_ev_demand_kw and total_available_kw > 0:
            strategy = 'DYNAMIC_MAX_RENEWABLE'
            ev_limit_kw = target_ev_demand_kw
        elif available_solar_kw > 0:
            strategy = 'DYNAMIC_ECO_SOLAR_ONLY'
            ev_limit_kw = min(available_solar_kw, target_ev_demand_kw)
        elif state.is_night_tariff and state.battery_soc < 40:
            strategy = 'CHARGE_BATTERY'
            ev_limit_kw = 0.0
        elif state.battery_soc < 20:
            strategy = 'PROTECT_BATTERY'
            ev_limit_kw = 0.0
        else:
            strategy = 'FAST_CHARGE_GRID'
            ev_limit_kw = target_ev_demand_kw

        per_station_limit_kw = round(ev_limit_kw / target_ev_sessions, 2) if target_ev_sessions else 0.0
        allocation_plan = {
            'mode': strategy,
            'ev_charge_limit_kw': round(ev_limit_kw, 2),
            'per_station_limit_kw': per_station_limit_kw,
            'available_solar_kw': round(available_solar_kw, 2),
            'battery_support_kw': round(battery_support_kw, 2),
            'target_ev_sessions': target_ev_sessions,
            'target_ev_demand_kw': round(target_ev_demand_kw, 2),
        }
        return EnergyDecision(strategy=strategy, allocation_plan=allocation_plan, state=state)

    def evaluate_current_decision(self) -> EnergyDecision:
        state = self._build_state()
        target_sessions = max(state.active_ev_sessions, 1)
        target_demand_kw = state.total_ev_demand_kw if state.total_ev_demand_kw > 0 else 11.0
        return self._decide_strategy(state, target_sessions, target_demand_kw)

    def evaluate_capacity_scenario(self, target_ev_sessions: int, target_ev_demand_kw: float) -> EnergyDecision:
        state = self._build_state()
        return self._decide_strategy(state, max(int(target_ev_sessions), 0), max(float(target_ev_demand_kw), 0.0))