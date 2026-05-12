from typing import List

from .conditions import ConstraintState, EVSession, EVSessionAllocation, EnergyAllocationPlan, SystemState


class PowerAllocationEngine:
    """Distributes available energy across EV sessions before any strategy label is derived."""

    @classmethod
    def allocate(cls, state: SystemState, constraints: ConstraintState) -> EnergyAllocationPlan:
        sessions = state.resolved_ev_sessions()
        if constraints.charging_paused or not sessions:
            return EnergyAllocationPlan(
                pv_to_ev_kw=0.0,
                battery_to_ev_kw=0.0,
                grid_to_ev_kw=0.0,
                ev_charge_limit_kw=0.0,
                per_session_limit_kw=0.0,
                battery_discharge_allowed=constraints.battery_discharge_allowed_kw > 0,
                battery_discharge_limit_kw=constraints.battery_discharge_allowed_kw,
                grid_assist_allowed=constraints.grid_assist_allowed,
                selected_strategy="",
                site_headroom_kw=constraints.site_available_import_kw,
                session_allocations=[],
                constraint_labels=list(constraints.labels),
                summary="Charging is paused or there are no active EV sessions.",
            )

        net_pv_surplus_kw = max(0.0, state.pv_production_kw - state.building_load_kw)
        grid_capacity_kw = constraints.grid_assist_limit_kw if constraints.grid_assist_allowed else 0.0
        total_available_kw = net_pv_surplus_kw + constraints.battery_discharge_allowed_kw + grid_capacity_kw

        weighted_allocations = cls._allocate_sessions(sessions, total_available_kw)
        total_allocated_kw = round(sum(item.allocated_power_kw for item in weighted_allocations), 2)
        pv_to_ev_kw = min(net_pv_surplus_kw, total_allocated_kw)
        battery_to_ev_kw = min(max(total_allocated_kw - pv_to_ev_kw, 0.0), constraints.battery_discharge_allowed_kw)
        grid_to_ev_kw = max(total_allocated_kw - pv_to_ev_kw - battery_to_ev_kw, 0.0)
        per_session_limit_kw = total_allocated_kw / len(weighted_allocations) if weighted_allocations else 0.0

        return EnergyAllocationPlan(
            pv_to_ev_kw=round(pv_to_ev_kw, 2),
            battery_to_ev_kw=round(battery_to_ev_kw, 2),
            grid_to_ev_kw=round(grid_to_ev_kw, 2),
            ev_charge_limit_kw=round(total_allocated_kw, 2),
            per_session_limit_kw=round(per_session_limit_kw, 2),
            battery_discharge_allowed=constraints.battery_discharge_allowed_kw > 0,
            battery_discharge_limit_kw=round(constraints.battery_discharge_allowed_kw, 2),
            grid_assist_allowed=constraints.grid_assist_allowed,
            selected_strategy="",
            site_headroom_kw=round(constraints.site_available_import_kw, 2),
            session_allocations=[allocation.to_dict() for allocation in weighted_allocations],
            constraint_labels=list(constraints.labels),
            summary="",
        )

    @classmethod
    def _allocate_sessions(cls, sessions: List[EVSession], total_available_kw: float) -> List[EVSessionAllocation]:
        if total_available_kw <= 0:
            return [
                EVSessionAllocation(
                    session_id=session.session_id,
                    allocated_power_kw=0.0,
                    requested_power_kw=round(session.demand_kw(), 2),
                    priority_score=round(cls._priority_score(session), 2),
                )
                for session in sessions
            ]

        remaining = total_available_kw
        allocations = {session.session_id: 0.0 for session in sessions}
        unmet_sessions = {session.session_id: session for session in sessions}

        while remaining > 0.01 and unmet_sessions:
            weight_sum = sum(cls._priority_score(session) for session in unmet_sessions.values())
            if weight_sum <= 0:
                break

            progressed = False
            for session_id, session in list(unmet_sessions.items()):
                demand = session.demand_kw()
                remaining_need = max(0.0, demand - allocations[session_id])
                if remaining_need <= 0.01:
                    unmet_sessions.pop(session_id, None)
                    continue

                share = remaining * (cls._priority_score(session) / weight_sum)
                granted = min(remaining_need, share)
                if granted > 0:
                    allocations[session_id] += granted
                    progressed = True

            remaining = total_available_kw - sum(allocations.values())
            unmet_sessions = {
                session_id: session
                for session_id, session in unmet_sessions.items()
                if session.demand_kw() - allocations[session_id] > 0.01
            }
            if not progressed:
                break

        return [
            EVSessionAllocation(
                session_id=session.session_id,
                allocated_power_kw=round(allocations[session.session_id], 2),
                requested_power_kw=round(session.demand_kw(), 2),
                priority_score=round(cls._priority_score(session), 2),
            )
            for session in sessions
        ]

    @staticmethod
    def _priority_score(session: EVSession) -> float:
        if session.priority is not None:
            return max(0.1, session.priority)

        soc_component = 2.0 - min((session.vehicle_soc or 50.0) / max(session.target_soc, 1.0), 1.5)
        departure_component = 1.0
        if session.estimated_departure_hours is not None:
            departure_component = 1.0 + max(0.0, (6.0 - min(session.estimated_departure_hours, 6.0))) / 3.0
        demand_component = max(0.5, min(session.demand_kw(), 22.0) / 11.0)
        return round(max(0.1, soc_component + departure_component + demand_component), 3)