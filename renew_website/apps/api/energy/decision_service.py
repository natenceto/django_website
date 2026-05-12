from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils import timezone

from renew_website.apps.algorithm.conditions import EVSession, SystemState
from renew_website.apps.algorithm.engine import DecisionEngine
from renew_website.apps.api.weather.intelligence import WeatherScoringService
from renew_website.apps.api.weather.models import WeatherLog
from renew_website.apps.charging_stations.models import MeterValue, Transaction

from .models import InverterReading


@dataclass
class EMSDecision:
    state: Optional[SystemState]
    constraint_state: Dict[str, Any]
    allocation_plan: Dict[str, Any]
    strategy: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy': self.strategy,
            'allocation_plan': self.allocation_plan,
            'constraint_state': self.constraint_state,
            'state': self.state,
        }


class EnergyOrchestrator:
    """Single source of truth for EMS state aggregation and decision evaluation."""

    def build_current_state(self) -> Optional[SystemState]:
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        if not latest_reading:
            return None

        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        weather_intelligence = WeatherScoringService.calculate(latest_weather)
        station_data = latest_reading.station_data or {}
        current_hour = timezone.localtime().hour
        ev_sessions = self._build_ev_sessions()
        total_ev_demand_kw = sum(session.demand_kw() for session in ev_sessions)

        return SystemState(
            battery_soc=float(latest_reading.battery_soc or 0.0),
            is_grid_available=bool(float(station_data.get('grid_voltage', 230.0) or 230.0) > 190.0),
            pv_production_kw=float(latest_reading.generation_power or 0.0) / 1000.0,
            building_load_kw=float(station_data.get('load_power', 0.0) or 0.0) / 1000.0,
            active_ev_sessions=len(ev_sessions),
            total_ev_demand_kw=round(total_ev_demand_kw, 2),
            cloud_cover_percent=float(getattr(latest_weather, 'cloud_cover', 0.0) or 0.0),
            is_raining=float(getattr(latest_weather, 'precipitation_mm', 0.0) or 0.0) > 0,
            weather_condition='rain' if float(getattr(latest_weather, 'precipitation_mm', 0.0) or 0.0) > 0.1 else ('cloudy' if float(getattr(latest_weather, 'cloud_cover', 0.0) or 0.0) > 50 else 'clear'),
            is_night_tariff=(current_hour >= 22 or current_hour < 6),
            weather_solar_score=weather_intelligence.solar_reliability_score,
            weather_risk_score=weather_intelligence.grid_dependency_risk,
            weather_confidence=weather_intelligence.confidence,
            ev_sessions=ev_sessions,
            forecasted_pv_kw_30m=(float(latest_reading.generation_power or 0.0) / 1000.0) * weather_intelligence.expected_pv_factor,
            site_max_import_kw=float(getattr(settings, 'EMS_SITE_MAX_IMPORT_KW', 0.0) or 0.0),
            main_breaker_limit_kw=float(getattr(settings, 'EMS_MAIN_BREAKER_LIMIT_KW', 0.0) or 0.0),
            grid_policy_preference=str(getattr(settings, 'EMS_GRID_POLICY', 'disabled') or 'disabled').lower(),
        )

    def evaluate_current_decision(self) -> EMSDecision:
        state = self.build_current_state()
        if not state:
            return EMSDecision(
                state=None,
                constraint_state={'labels': ['No Telemetry']},
                allocation_plan={
                    'pv_to_ev_kw': 0.0,
                    'battery_to_ev_kw': 0.0,
                    'grid_to_ev_kw': 0.0,
                    'ev_charge_limit_kw': 0.0,
                    'per_session_limit_kw': 0.0,
                    'battery_discharge_allowed': False,
                    'battery_discharge_limit_kw': 0.0,
                    'grid_assist_allowed': False,
                    'selected_strategy': '',
                    'constraint_labels': ['No Telemetry'],
                    'summary': 'No inverter telemetry available.',
                    'session_allocations': [],
                },
                strategy=None,
            )

        decision = DecisionEngine.evaluate(state)
        return EMSDecision(
            state=state,
            constraint_state=decision.get('constraint_state', {}),
            allocation_plan=decision.get('allocation_plan', {}),
            strategy=decision.get('strategy') or decision.get('mode'),
        )

    def evaluate_capacity_scenario(self, active_sessions: int, requested_demand_kw: float) -> EMSDecision:
        base_state = self.build_current_state()
        if not base_state:
            return self.evaluate_current_decision()

        per_session_kw = requested_demand_kw / active_sessions if active_sessions else 0.0
        synthetic_sessions = [
            EVSession(
                session_id=f'scenario-{index + 1}',
                vehicle_soc=50.0,
                requested_power_kw=per_session_kw,
                max_acceptance_kw=per_session_kw,
                target_soc=80.0,
                estimated_departure_hours=4.0,
                priority=1.0,
            )
            for index in range(active_sessions)
        ]
        scenario_state = replace(
            base_state,
            active_ev_sessions=active_sessions,
            total_ev_demand_kw=requested_demand_kw,
            ev_sessions=synthetic_sessions,
        )
        decision = DecisionEngine.evaluate(scenario_state)
        return EMSDecision(
            state=scenario_state,
            constraint_state=decision.get('constraint_state', {}),
            allocation_plan=decision.get('allocation_plan', {}),
            strategy=decision.get('strategy') or decision.get('mode'),
        )

    def _build_ev_sessions(self) -> List[EVSession]:
        active_transactions = Transaction.objects.filter(stopped_at__isnull=True).select_related('connector__station')
        sessions: List[EVSession] = []

        for transaction in active_transactions:
            latest_meter = transaction.meter_values.order_by('-timestamp').first()
            requested_power_kw = self._coerce_kw(transaction.requested_power_kw)
            connector_limit_kw = self._coerce_kw(transaction.connector.max_power_kw)
            data = latest_meter.data if latest_meter and isinstance(latest_meter.data, dict) else {}
            session_context = data.get('session_context', {}) if isinstance(data, dict) else {}

            sessions.append(
                EVSession(
                    session_id=str(transaction.transaction_id or transaction.id),
                    vehicle_soc=(
                        float(latest_meter.soc_percentage)
                        if latest_meter and latest_meter.soc_percentage is not None
                        else self._coerce_optional_float(session_context.get('vehicle_soc'))
                    ),
                    requested_power_kw=requested_power_kw or self._coerce_kw(session_context.get('requested_power_kw')) or connector_limit_kw,
                    max_acceptance_kw=self._coerce_kw(session_context.get('max_acceptance_kw')) or connector_limit_kw,
                    target_soc=float(session_context.get('target_soc', 80.0) or 80.0),
                    estimated_departure_hours=self._coerce_optional_float(session_context.get('estimated_departure_hours')),
                    priority=self._coerce_optional_float(session_context.get('priority_weight')),
                )
            )

        return sessions

    @staticmethod
    def _coerce_kw(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        return float(value or 0.0)

    @staticmethod
    def _coerce_optional_float(value: Any) -> Optional[float]:
        if value in (None, ''):
            return None
        return float(value)