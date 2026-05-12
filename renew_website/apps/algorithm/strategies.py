from .conditions import ConstraintState, EnergyAllocationPlan, SystemState
from .work_modes import SystemWorkMode


class StrategyResolver:
    """Maps an already-built allocation plan to a human-readable EMS strategy label."""

    @classmethod
    def resolve(cls, state: SystemState, constraints: ConstraintState, allocation: EnergyAllocationPlan):
        if constraints.emergency_reserve_active:
            return SystemWorkMode.EMERGENCY_BACKUP
        if constraints.charging_paused and state.is_night_tariff:
            return SystemWorkMode.PROTECT_BATTERY
        if constraints.charging_paused:
            return SystemWorkMode.CHARGE_BATTERY
        if allocation.grid_to_ev_kw > 0:
            return SystemWorkMode.FAST_CHARGE_GRID
        if allocation.pv_to_ev_kw > 0 and allocation.battery_to_ev_kw > 0:
            return SystemWorkMode.DYNAMIC_MAX_RENEWABLE
        return SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY