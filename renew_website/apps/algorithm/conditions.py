from dataclasses import dataclass
from typing import Optional

@dataclass
class SystemState:
    """Holds the real-time snapshot of the entire microgrid system."""
    # Hardware stats
    battery_soc: float              # Battery State of Charge (0 - 100%)
    is_grid_available: bool         # True if grid is connected
    pv_production_kw: float         # Current solar power generation
    building_load_kw: float         # Actual current building consumption (EXCLUDING EV chargers)
    
    # EV stats
    active_ev_sessions: int         # How many cars are currently plugged in
    total_ev_demand_kw: float       # How much power the EVs *want* to draw right now (e.g. 2 x 11kW = 22kW)
    
    # Weather & Time stats
    cloud_cover_percent: float      # Cloudiness (0 - 100%)
    is_raining: bool                # True if currently raining
    weather_condition: str          # string representation like 'sunny', 'cloudy'
    is_night_tariff: bool           # True if current time is within cheap grid tariff window


def is_sun_reliable(state: SystemState) -> bool:
    """
    Determines if we can rely on sustained solar generation soon.
    If it's raining or very cloudy, we cannot drain the battery thinking the sun will save us.
    """
    if state.is_raining:
        return False
    if state.cloud_cover_percent >= 60.0:
        return False
    return True


def get_safe_battery_discharge_limit(state: SystemState) -> float:
    """
    Returns how much power (kW) we are allowed to drain from the battery RIGHT NOW to help EVs.
    This changes based on the weather!
    If the weather is bad (rain/clouds), we protect the battery heavily (e.g., stop at 35-40%).
    If the weather is sunny, we can drain it more (e.g., down to 20%), knowing the sun will recharge it.
    """
    # Max inverter battery discharge limit (e.g. 5kW inverter standard limit = 5kW)
    MAX_DISCHARGE_KW = 5.0 
    
    # 1. If grid is down, battery is strictly for the building! 0kW for EVs.
    if not state.is_grid_available:
        return 0.0
        
    # 2. Define minimum allowed SOC based on weather
    min_allowed_soc = 20.0  # Sunny baseline (can go low)
    if not is_sun_reliable(state):
        min_allowed_soc = 35.0  # Protect heavily if weather is bad
        
    if state.is_night_tariff:
        min_allowed_soc = 50.0  # Don't drain battery during night tariff, we might need it for tomorrow

    # 3. Calculate available buffer
    if state.battery_soc <= min_allowed_soc:
        return 0.0 # No battery power allowed for EVs

    # We have surplus SOC. We linearly scale allowed discharge based on how full the battery is.
    # Example: If min is 35 and we are at 40, we allow a tiny bit. If at 100, we allow Max.
    surplus_soc = state.battery_soc - min_allowed_soc
    scale_factor = min(surplus_soc / 30.0, 1.0) # 30% above minimum unlocks full discharge power
    
    return MAX_DISCHARGE_KW * scale_factor
