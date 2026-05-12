from typing import Dict, Any
from .allocation import PowerAllocationEngine
from .conditions import SystemState
from .constraints import ConstraintEngine
from .execution import ExecutionPlanner
from .strategies import StrategyResolver

class DecisionEngine:
    """
    Stable facade over the EMS pipeline: constraints -> allocation -> strategy label.
    """

    @classmethod
    def evaluate(cls, state: SystemState) -> Dict[str, Any]:
        """
        Returns a dictionary containing:
        - 'strategy': SystemWorkMode
        - 'allocation_plan': explicit EMS execution plan
        """
        constraints = ConstraintEngine.evaluate(state)
        allocation = PowerAllocationEngine.allocate(state, constraints)
        strategy = StrategyResolver.resolve(state, constraints, allocation)
        finalized_plan = ExecutionPlanner.finalize(allocation, constraints, strategy)
        return {
            "mode": strategy,
            "strategy": strategy,
            "ev_power_limit_kw": finalized_plan.ev_charge_limit_kw,
            "allocation_plan": finalized_plan.to_dict(),
            "constraint_state": constraints.to_dict(),
        }
