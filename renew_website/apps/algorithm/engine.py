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
            return {
                "mode": SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY, # Default fallback
                "ev_power_limit_kw": 0.0
            }

        # --- Dynamic Mode Selection ---
        # We want to fast charge EVs (especially up to 80%) as fast as possible 
        # relying purely on Renewables (PV + Battery) IF weather is good.
        
        # Determine battery buffer state explicitly
        is_weather_good = is_sun_reliable(state)
        # Assuming battery > 60% means it's safe to use for aggressive EV charging
        is_battery_optimally_full = state.battery_soc > 60.0
        
        mode = SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY
        
        if is_weather_good and is_battery_optimally_full:
            # We have good weather and full-enough batteries -> Max Renewable Power to the EV
            mode = SystemWorkMode.DYNAMIC_MAX_RENEWABLE
        elif is_weather_good and not is_battery_optimally_full:
            # We have good weather, but battery is not full enough -> Don't drain it via limit
            # Limit strictly to PV surplus to protect battery filling up
            allowed_battery_discharge_kw = 0.0
            available_eco_power_kw = net_pv_surplus_kw
            mode = SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY
        elif not is_weather_good and state.battery_soc > 20.0:
            # Bad weather, but we still have a bit of buffer
            # Keep battery discharge at whatever `get_safe_battery_discharge_limit` said
            mode = SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY
            
        return {
            "mode": mode,
            "ev_power_limit_kw": available_eco_power_kw
        }
