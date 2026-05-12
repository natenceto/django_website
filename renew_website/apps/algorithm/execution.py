from .conditions import ConstraintState, EnergyAllocationPlan


class ExecutionPlanner:
    """Annotates an allocation plan with operator-facing summary fields."""

    @classmethod
    def finalize(cls, allocation: EnergyAllocationPlan, constraints: ConstraintState, strategy_label: str) -> EnergyAllocationPlan:
        allocation.selected_strategy = strategy_label
        allocation.constraint_labels = list(dict.fromkeys([*allocation.constraint_labels, *constraints.labels]))

        session_summary = ""
        if allocation.session_allocations:
            session_summary = ", ".join(
                f"{session['session_id']}: {session['allocated_power_kw']:.2f} kW"
                for session in allocation.session_allocations
            )

        allocation.summary = (
            f"PV {allocation.pv_to_ev_kw:.2f} kW, Battery {allocation.battery_to_ev_kw:.2f} kW, "
            f"Grid {allocation.grid_to_ev_kw:.2f} kW to EV load. "
            f"Per-session limit {allocation.per_session_limit_kw:.2f} kW."
        )
        if session_summary:
            allocation.summary = f"{allocation.summary} Session split: {session_summary}."

        return allocation