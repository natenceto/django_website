from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Dict, Optional, Union

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from renew_website.apps.charging_stations.models import CommandLog
from renew_website.tasks import mark_command_timeout


logger = logging.getLogger("charging_stations.command_bus")
COMMAND_TIMEOUT_SECONDS = 45


class CommandDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class StartChargingCommand:
    station_id: int
    connector_id: int
    id_tag: str
    requested_power_kw: Optional[Union[int, float]] = None
    session_context: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StopChargingCommand:
    station_id: int
    transaction_id: int


@dataclass(frozen=True)
class CommandDispatchResult:
    station_id: int
    command_type: str
    dispatched: bool
    command_id: Optional[str] = None
    detail: str = ""


class OCPPService:
    def _channel_layer(self):
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.error("Channel layer not available for OCPP command dispatch")
            raise CommandDispatchError("Channel layer not available for OCPP command dispatch")
        return channel_layer

    def dispatch_start(self, command: StartChargingCommand, command_id: str) -> CommandDispatchResult:
        message = {
            "type": "remote_start_transaction",
            "station_id": command.station_id,
            "connector_id": command.connector_id,
            "id_tag": command.id_tag,
            "requested_power": command.requested_power_kw,
            "session_context": command.session_context,
            "command_id": command_id,
        }
        async_to_sync(self._channel_layer().group_send)(
            f"charging_stations_group_{command.station_id}",
            message,
        )
        logger.info(
            "Dispatched start command: station=%s connector=%s",
            command.station_id,
            command.connector_id,
        )
        return CommandDispatchResult(
            station_id=command.station_id,
            command_type="start_charging",
            dispatched=True,
            command_id=command_id,
            detail="RemoteStartTransaction dispatched",
        )

    def dispatch_stop(self, command: StopChargingCommand, command_id: str) -> CommandDispatchResult:
        message = {
            "type": "remote_stop_transaction",
            "station_id": command.station_id,
            "transaction_id": command.transaction_id,
            "command_id": command_id,
        }
        async_to_sync(self._channel_layer().group_send)(
            f"charging_stations_group_{command.station_id}",
            message,
        )
        logger.info(
            "Dispatched stop command: station=%s transaction=%s",
            command.station_id,
            command.transaction_id,
        )
        return CommandDispatchResult(
            station_id=command.station_id,
            command_type="stop_charging",
            dispatched=True,
            command_id=command_id,
            detail="RemoteStopTransaction dispatched",
        )


class CommandBus:
    def __init__(self, ocpp_service: Optional[OCPPService] = None):
        self.ocpp_service = ocpp_service or OCPPService()

    def _create_log(self, command: Union[StartChargingCommand, StopChargingCommand]) -> CommandLog:
        return CommandLog.objects.create(
            station_id=command.station_id,
            command_type=type(command).__name__,
            payload=asdict(command),
            status="pending",
            detail="Command created and queued for transport dispatch",
        )

    def _mark_sent(self, command_log: CommandLog, result: CommandDispatchResult) -> CommandDispatchResult:
        command_log.status = "sent"
        command_log.detail = result.detail
        command_log.executed_at = timezone.now()
        command_log.save(update_fields=["status", "detail", "executed_at"])
        mark_command_timeout.apply_async(kwargs={"command_id": str(command_log.command_id)}, countdown=COMMAND_TIMEOUT_SECONDS)
        return CommandDispatchResult(
            station_id=result.station_id,
            command_type=result.command_type,
            dispatched=result.dispatched,
            command_id=str(command_log.command_id),
            detail=result.detail,
        )

    def _mark_failed(self, command_log: CommandLog, exc: Exception) -> None:
        command_log.status = "failed"
        command_log.error_message = str(exc)
        command_log.detail = "Transport dispatch failed"
        command_log.executed_at = timezone.now()
        command_log.save(update_fields=["status", "error_message", "detail", "executed_at"])

    def dispatch(self, command: Union[StartChargingCommand, StopChargingCommand]) -> CommandDispatchResult:
        command_log = self._create_log(command)
        try:
            if isinstance(command, StartChargingCommand):
                return self._mark_sent(command_log, self.ocpp_service.dispatch_start(command, str(command_log.command_id)))
            if isinstance(command, StopChargingCommand):
                return self._mark_sent(command_log, self.ocpp_service.dispatch_stop(command, str(command_log.command_id)))
            raise CommandDispatchError(f"Unsupported command type: {type(command).__name__}")
        except Exception as exc:
            self._mark_failed(command_log, exc)
            if isinstance(exc, CommandDispatchError):
                raise
            raise CommandDispatchError(str(exc)) from exc


command_bus = CommandBus()