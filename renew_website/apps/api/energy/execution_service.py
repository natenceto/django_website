from __future__ import annotations

from dataclasses import dataclass, field

from renew_website.apps.charging_stations.models import Transaction
from renew_website.apps.charging_stations.tasks import set_charging_power_limit


@dataclass(slots=True)
class EMSExecutionResult:
    success: bool
    message: str
    stations_updated: int = 0
    total_connectors_updated: int = 0
    applied_ev_limit_kw: float = 0.0
    updated_connectors: list[str] = field(default_factory=list)
    skipped_connectors: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'message': self.message,
            'stations_updated': self.stations_updated,
            'total_connectors_updated': self.total_connectors_updated,
            'applied_ev_limit_kw': round(float(self.applied_ev_limit_kw or 0.0), 2),
            'updated_connectors': self.updated_connectors,
            'skipped_connectors': self.skipped_connectors,
            'errors': self.errors,
        }


class EMSExecutionService:
    """Apply an EMS allocation plan to active charging sessions."""

    def apply_allocation_plan(self, allocation_plan: dict | None) -> EMSExecutionResult:
        allocation_plan = allocation_plan or {}
        ev_limit_kw = float(allocation_plan.get('ev_charge_limit_kw') or 0.0)

        active_transactions = list(
            Transaction.objects.filter(status='active').select_related('connector__station')
        )
        if not active_transactions:
            return EMSExecutionResult(
                success=False,
                message='No active charging sessions to update',
                applied_ev_limit_kw=ev_limit_kw,
            )

        station_ids = sorted({transaction.connector.station_id for transaction in active_transactions})
        per_station_limit_kw = float(
            allocation_plan.get('per_station_limit_kw') or (ev_limit_kw / len(station_ids) if station_ids else 0.0)
        )
        power_limit_watts = int(round(per_station_limit_kw * 1000))

        updated_connectors: list[str] = []
        errors: list[str] = []
        for station_id in station_ids:
            try:
                set_charging_power_limit(station_id, power_limit_watts)
                station_transactions = [tx for tx in active_transactions if tx.connector.station_id == station_id]
                for transaction in station_transactions:
                    updated_connectors.append(f'{station_id}:{transaction.connector.connector_id}')
            except Exception as exc:
                errors.append(f'Station {station_id}: {exc}')

        success = not errors
        return EMSExecutionResult(
            success=success,
            message='EMS allocation plan applied' if success else 'EMS allocation plan applied with errors',
            stations_updated=len(station_ids) - len(errors),
            total_connectors_updated=len(updated_connectors),
            applied_ev_limit_kw=ev_limit_kw,
            updated_connectors=updated_connectors,
            skipped_connectors=[],
            errors=errors,
        )