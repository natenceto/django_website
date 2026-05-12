"""Energy management utility functions."""
import logging

from .decision_service import EnergyOrchestrator

logger = logging.getLogger(__name__)

def run_work_mode_algorithm(inverter=None):
    """
    Determines the optimal EMS strategy and execution plan based on current conditions.
    """
    decision = EnergyOrchestrator().evaluate_current_decision()
    return {
        'strategy': decision.strategy,
        'allocation_plan': decision.allocation_plan,
        'constraint_state': decision.constraint_state,
        'state': decision.state,
    }
