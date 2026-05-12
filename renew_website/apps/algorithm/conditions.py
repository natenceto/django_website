from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

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
    weather_solar_score: float = 0.5
    weather_risk_score: float = 0.5
    weather_confidence: float = 0.0
    ev_sessions: List["EVSession"] = field(default_factory=list)
    forecasted_pv_kw_30m: Optional[float] = None
    forecasted_pv_kw_2h: Optional[float] = None
    site_max_import_kw: Optional[float] = None
    site_max_export_kw: Optional[float] = None
    main_breaker_limit_kw: Optional[float] = None
    grid_policy_preference: str = "disabled"

    def resolved_ev_sessions(self) -> List["EVSession"]:
        if self.ev_sessions:
            return self.ev_sessions

        if self.active_ev_sessions <= 0:
            return []

        requested_per_session = self.total_ev_demand_kw / self.active_ev_sessions if self.active_ev_sessions else 0.0
        return [
            EVSession(
                session_id=f"session-{index + 1}",
                vehicle_soc=None,
                requested_power_kw=requested_per_session,
                max_acceptance_kw=requested_per_session,
                target_soc=80.0,
                estimated_departure_hours=None,
                priority=None,
            )
            for index in range(self.active_ev_sessions)
        ]


@dataclass
class EVSession:
    """First-class EV charging demand object for weighted allocation."""
    session_id: str
    vehicle_soc: Optional[float]
    requested_power_kw: float
    max_acceptance_kw: float
    target_soc: float = 80.0
    estimated_departure_hours: Optional[float] = None
    priority: Optional[float] = None

    def demand_kw(self) -> float:
        return max(0.0, min(self.requested_power_kw, self.max_acceptance_kw))


@dataclass
class EVSessionAllocation:
    session_id: str
    allocated_power_kw: float
    requested_power_kw: float
    priority_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BatteryDischargeDecision:
    """Allowed battery contribution for EV charging under the current constraints."""
    allowed_kw: float
    reason: str
    protection_active: bool
    min_allowed_soc: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConstraintState:
    """What the EMS is allowed to do right now, independent from strategy labeling."""
    battery_discharge_allowed_kw: float
    grid_assist_allowed: bool
    grid_assist_limit_kw: float
    pv_priority_required: bool
    emergency_reserve_active: bool
    charging_paused: bool
    site_available_import_kw: float
    battery_decision: BatteryDischargeDecision
    labels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["battery_decision"] = self.battery_decision.to_dict()
        return data


@dataclass
class EnergyAllocationPlan:
    """Execution-ready EMS plan produced by the strategy engine."""
    pv_to_ev_kw: float
    battery_to_ev_kw: float
    grid_to_ev_kw: float
    ev_charge_limit_kw: float
    per_session_limit_kw: float
    battery_discharge_allowed: bool
    battery_discharge_limit_kw: float
    grid_assist_allowed: bool
    selected_strategy: str
    site_headroom_kw: float = 0.0
    session_allocations: List[Dict[str, Any]] = field(default_factory=list)
    constraint_labels: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def is_sun_reliable(state: SystemState) -> bool:
    """
    Determines if we can rely on sustained solar generation soon.
    If it's raining or very cloudy, we cannot drain the battery thinking the sun will save us.
    """
    if state.weather_confidence > 0:
        return state.weather_solar_score >= 0.6
    if state.is_raining:
        return False
    if state.cloud_cover_percent >= 60.0:
        return False
    return True


def get_safe_battery_discharge_limit(state: SystemState) -> BatteryDischargeDecision:
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
        return BatteryDischargeDecision(
            allowed_kw=0.0,
            reason="Grid unavailable, reserve battery for site load",
            protection_active=True,
            min_allowed_soc=100.0,
        )
        
    # 2. Define absolute minimum allowed SOC
    min_allowed_soc = 35.0  # Absolute hard minimum - never drain below this
    
    if not is_sun_reliable(state):
        min_allowed_soc = 40.0  # Protect heavily if weather is bad, raise minimum
        
    if state.is_night_tariff:
        min_allowed_soc = 50.0  # Don't drain battery during night tariff, we might need it for tomorrow

    # 3. Calculate available buffer
    if state.battery_soc <= min_allowed_soc:
        # Prevent any discharging if below the hard minimum
        return BatteryDischargeDecision(
            allowed_kw=0.0,
            reason="Battery reserve protection active",
            protection_active=True,
            min_allowed_soc=min_allowed_soc,
        )

    # We do not want to *re-engage* the battery intensely if it's just barely fluttering at 36-39%.
    # We scale the discharge based on how far above the minimum we are.
    # At exactly minimum (35%), power = 0.
    # We fully unlock max discharge at minimum + 5% (e.g. 40%).
    surplus_soc = state.battery_soc - min_allowed_soc
    scale_factor = min(surplus_soc / 5.0, 1.0) # Ramp up smoothly from 35 to 40
    
    protection_reason = "Battery assist available"
    if state.is_night_tariff:
        protection_reason = "Night tariff reserve active"
    elif not is_sun_reliable(state):
        protection_reason = "Cloud/rain protection limiting discharge"

    weather_multiplier = 1.0
    if state.weather_confidence > 0:
        weather_multiplier = max(0.2, min(state.weather_solar_score, 1.0))

    return BatteryDischargeDecision(
        allowed_kw=MAX_DISCHARGE_KW * scale_factor * weather_multiplier,
        reason=protection_reason,
        protection_active=min_allowed_soc > 35.0,
        min_allowed_soc=min_allowed_soc,
    )
