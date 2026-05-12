from dataclasses import asdict, dataclass
from typing import Any, Dict

from renew_website.apps.api.deye.control import build_modbus_commands_for_allocation
from renew_website.apps.api.deye.manager import DeyeManager
from renew_website.apps.charging_stations.models import Station, Transaction
from renew_website.apps.charging_stations.tasks import set_charging_power_limit


@dataclass
class EMSExecutionResult:
    success: bool
    stations_updated: int
    charger_limit_kw: float
    inverter_policy_changed: bool
    modbus_constraints_applied: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EMSExecutionService:
    """Single actuator orchestration service for EMS allocation plans."""

    def apply_allocation_plan(self, allocation_plan: Dict[str, Any]) -> EMSExecutionResult:
        active_transactions = Transaction.objects.filter(stopped_at__isnull=True)
        station_ids = active_transactions.values_list('connector__station_id', flat=True)
        active_stations = Station.objects.filter(id__in=station_ids).distinct()

        per_station_power_kw = float(allocation_plan.get('per_session_limit_kw', 0.0) or 0.0)
        power_watts = int(per_station_power_kw * 1000)

        for station in active_stations:
            set_charging_power_limit.delay(station.id, power_watts)

        modbus_commands = build_modbus_commands_for_allocation(allocation_plan)
        modbus_applied = False
        if modbus_commands:
            manager = DeyeManager()
            modbus_applied = bool(manager.apply_modbus_commands(modbus_commands))
            if not modbus_applied:
                return EMSExecutionResult(
                    success=False,
                    stations_updated=active_stations.count(),
                    charger_limit_kw=per_station_power_kw,
                    inverter_policy_changed=False,
                    modbus_constraints_applied=False,
                    message='Failed to apply supported inverter constraint commands.',
                )

        return EMSExecutionResult(
            success=True,
            stations_updated=active_stations.count(),
            charger_limit_kw=per_station_power_kw,
            inverter_policy_changed=False,
            modbus_constraints_applied=bool(modbus_commands and modbus_applied),
            message='EMS allocation applied successfully.',
        )