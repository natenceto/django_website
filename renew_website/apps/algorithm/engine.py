from typing import Dict, Any
from .work_modes import SystemWorkMode
from .conditions import SystemState, is_sun_reliable, get_safe_battery_discharge_limit

class DecisionEngine:
    """
    Core brain of the energy logic. Evaluates real-time state and outputs
    both the chosen macro-mode AND the exact kW limit for the EV chargers.
    """

    @classmethod
    def evaluate(cls, state: SystemState) -> Dict[str, Any]:
        """
        Returns a dictionary containing:
        - 'mode': SystemWorkMode
        - 'ev_power_limit_kw': Allowed power for all EVs combined.
        """
        # 1. EMERGENCY: Grid is down. Island mode.
        if not state.is_grid_available:
            return {
                "mode": SystemWorkMode.EMERGENCY_BACKUP,
                "ev_power_limit_kw": 0.0 # Save all power for the building
            }

        # 2. NIGHT TARIFF PROTECTION: Preemptively fill battery for tomorrow, pause EVs
        # (Assuming you don't want EVs stealing cheap grid directly without control, 
        # or maybe you do? For now, we protect battery if it's very low)
        if state.is_night_tariff and state.battery_soc < 30.0:
            return {
                "mode": SystemWorkMode.PROTECT_BATTERY,
                "ev_power_limit_kw": 0.0 
            }

        # 3. STANDARD OPERATION: Calculate dynamic EV load limit
        return cls._calculate_dynamic_balances(state)

    @classmethod
    def _calculate_dynamic_balances(cls, state: SystemState) -> Dict[str, Any]:
        # Priority 1: Building.
        # How much PV is left AFTER the building takes what it needs?
        net_pv_surplus_kw = max(0.0, state.pv_production_kw - state.building_load_kw)

        # Priority 2: EVs & Priority 3: Batteries
        # Can we use the battery to help the EVs?
        allowed_battery_discharge_kw = get_safe_battery_discharge_limit(state)

        # The total power pool we have *specifically allowed* for EVs right now
        available_eco_power_kw = net_pv_surplus_kw + allowed_battery_discharge_kw

        if state.active_ev_sessions == 0:
            # Nobody is charging. Deye will automatically push `net_pv_surplus_kw` to batteries 
            # or clip it (Zero Export). EV limit is irrelevant, but we set it to 0.
            return {
                "mode": SystemWorkMode.ECO_CHARGE, # Default fallback
                "ev_power_limit_kw": 0.0
            }

        # If the user has manually pushed a "Fast Charge" button on the site
        # (Assuming we might pass this via state in the future, let's keep logic ready)
        # return {"mode": SystemWorkMode.FAST_CHARGE, "ev_power_limit_kw": 22.0 * state.active_ev_sessions}

        # Standard Smart Charging
        # We give the EVs exactly the allowed pool. 
        # If available_eco_power_kw is 0 (it's raining, night, battery low), stations pause.
        
        # Determine strictness of mode for database logging
        mode = SystemWorkMode.SMART_CHARGE if allowed_battery_discharge_kw > 0 else SystemWorkMode.ECO_CHARGE

        return {
            "mode": mode,
            "ev_power_limit_kw": available_eco_power_kw
        }
