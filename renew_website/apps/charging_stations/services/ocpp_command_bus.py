from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from renew_website.apps.charging_stations.registry import station_runtime


class CommandDispatchError(Exception):
    """Raised when an OCPP command cannot be dispatched to a station consumer."""


@dataclass(slots=True)
class StartChargingCommand:
    station_id: int
    connector_id: int
    id_tag: str
    requested_power_kw: float | int | None = None
    session_context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StopChargingCommand:
    station_id: int
    transaction_id: int | str


@dataclass(slots=True)
class CommandDispatchResult:
    command_id: UUID
    station_id: int
    event_type: str
    group_name: str


class CommandBus:
    """Thin channel-layer dispatcher for remote OCPP commands."""

    def dispatch(self, command: StartChargingCommand | StopChargingCommand) -> CommandDispatchResult:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            raise CommandDispatchError('Channel layer is not configured')

        station_id = int(command.station_id)
        if not station_runtime.is_online(station_id):
            raise CommandDispatchError(f'Station {station_id} is not connected')

        command_id = uuid4()
        group_name = f'charging_stations_group_{station_id}'

        if isinstance(command, StartChargingCommand):
            event_type = 'remote_start_transaction'
            payload = {
                'type': event_type,
                'command_id': str(command_id),
                'station_id': station_id,
                'connector_id': int(command.connector_id),
                'id_tag': command.id_tag,
                'requested_power': command.requested_power_kw,
                'session_context': dict(command.session_context or {}),
            }
        elif isinstance(command, StopChargingCommand):
            event_type = 'remote_stop_transaction'
            payload = {
                'type': event_type,
                'command_id': str(command_id),
                'station_id': station_id,
                'transaction_id': command.transaction_id,
            }
        else:
            raise CommandDispatchError(f'Unsupported command type: {type(command).__name__}')

        try:
            async_to_sync(channel_layer.group_send)(group_name, payload)
        except Exception as exc:
            raise CommandDispatchError(f'Failed to dispatch command: {exc}') from exc

        return CommandDispatchResult(
            command_id=command_id,
            station_id=station_id,
            event_type=event_type,
            group_name=group_name,
        )


command_bus = CommandBus()