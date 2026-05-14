# consumers.py
import asyncio
import json
import logging
import datetime as py_datetime
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, Union, Optional, Tuple

from django.conf import settings
from django.utils import timezone
from django.db import transaction as db_transaction
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from ocpp import exceptions as ocpp_exceptions
from ocpp.routing import on
from ocpp.v16 import ChargePoint as OCPPChargePoint
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (
    RegistrationStatus,
    Action,
    AuthorizationStatus,
    AvailabilityType,
    ResetType,
)

from .logging_config import get_ocpp_logger, get_station_logger
from .models import Station, Connector, Transaction, UserRFID, MeterValue, CommandLog, Vehicle
from .registry import ACTIVE_STATIONS, station_runtime


def _snake_to_camel_case(value: str) -> str:
    if not isinstance(value, str) or "_" not in value:
        return value
    first, *rest = value.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest if part)


def _ws_close_reason(close_code: Optional[int]) -> str:
    close_reasons = {
        1000: "normal_closure",
        1001: "going_away",
        1002: "protocol_error",
        1003: "unsupported_data",
        1005: "no_status_received",
        1006: "abnormal_closure",
        1007: "invalid_payload_data",
        1008: "policy_violation",
        1009: "message_too_big",
        1010: "mandatory_extension_missing",
        1011: "internal_error",
        1012: "service_restart",
        1013: "try_again_later",
        1015: "tls_handshake_failure",
    }
    return close_reasons.get(close_code, "unknown")


# -------------------------
# Logging
# -------------------------
ocpp_logger = get_ocpp_logger("consumers")
logger = logging.getLogger("charging_stations")


def _ocpp_configuration_timeout_seconds() -> float:
    return float(getattr(settings, "OCPP_CONFIGURATION_TIMEOUT_SECONDS", 10.0))


def _ocpp_station_configuration_defaults() -> Dict[str, str]:
    configured = getattr(settings, "OCPP_STATION_CONFIGURATION", {}) or {}
    defaults = {
        "HeartbeatInterval": "60",
        "MeterValueSampleInterval": "30",
        "ClockAlignedDataInterval": "0",
        "MeterValuesSampledData": (
            "Energy.Active.Import.Register,Power.Active.Import,Current.Import,Voltage"
        ),
    }
    merged = {**defaults, **configured}

    sampled_data = merged.get("MeterValuesSampledData", defaults["MeterValuesSampledData"])
    if isinstance(sampled_data, (list, tuple)):
        sampled_data = ",".join(str(item) for item in sampled_data if item)
    merged["MeterValuesSampledData"] = str(sampled_data)

    for numeric_key in ("HeartbeatInterval", "MeterValueSampleInterval", "ClockAlignedDataInterval"):
        merged[numeric_key] = str(merged[numeric_key])

    return merged


# -------------------------
# Heartbeat throttling state
# -------------------------
_last_heartbeat_log: Dict[Union[int, str], py_datetime.datetime] = {}
_last_heartbeat_db_update: Dict[Union[int, str], py_datetime.datetime] = {}
_rapid_heartbeat_count: Dict[Union[int, str], Dict[str, Any]] = {}


# -------------------------
# WebSocket Performance Tracking
# -------------------------
_ws_performance_stats: Dict[Union[int, str], Dict[str, Any]] = {}
_ws_metric_db_cache: Dict[Union[int, str], Any] = {}  # Cache DB metric objects

def track_ws_performance(station_id: str, message_size: int, direction: str):
    """
    Track WebSocket performance metrics in memory and periodically save to database.
    """
    now = timezone.now()
    
    if station_id not in _ws_performance_stats:
        _ws_performance_stats[station_id] = {
            'messages_sent': 0,
            'messages_received': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'last_activity': now,
            'connection_start': now,
            'db_save_count': 0,  # Track how many times we've saved to DB
        }
    
    stats = _ws_performance_stats[station_id]
    stats['last_activity'] = now
    
    if direction == 'sent':
        stats['messages_sent'] += 1
        stats['bytes_sent'] += message_size
    elif direction == 'received':
        stats['messages_received'] += 1
        stats['bytes_received'] += message_size
    
    # Save to database periodically (every 100 messages or at least every 60 seconds)
    total_messages = stats['messages_sent'] + stats['messages_received']
    last_save_seconds = (now - stats['connection_start']).total_seconds()
    
    should_save = (
        (total_messages % 100 == 0) or  # Every 100 messages
        (stats['db_save_count'] == 0 and last_save_seconds >= 5) or  # First save after 5 seconds
        (stats['db_save_count'] > 0 and last_save_seconds >= (stats['db_save_count'] * 60))  # Then every 60 seconds
    )
    
    if should_save:
        try:
            _save_ws_metric_to_db(station_id, stats)
            stats['db_save_count'] += 1
        except Exception as e:
            get_station_logger(station_id).warning(f"Failed to save WebSocket metric to DB: {e}")


def _save_ws_metric_to_db(station_id: Union[int, str], stats: Dict[str, Any]):
    """Save WebSocket performance metric to database (async-friendly)."""
    return
    
    try:
        station_id_int = int(station_id)
        station = Station.objects.filter(id=station_id_int).first()
        if not station:
            return
        
        # Get or create metric record
        metric = _ws_metric_db_cache.get(station_id)
        if not metric:
            # Try to get active metric from DB
            metric = WebSocketPerformanceMetric.objects.filter(
                station_id=station_id_int,
                is_active=True
            ).order_by('-connection_start').first()
            
            # If no active metric or it's too old, create new one
            if not metric:
                metric = WebSocketPerformanceMetric.objects.create(
                    station=station,
                    connection_start=stats['connection_start']
                )
            
            _ws_metric_db_cache[station_id] = metric
        
        # Update metric fields
        metric.messages_sent = stats['messages_sent']
        metric.messages_received = stats['messages_received']
        metric.bytes_sent = stats['bytes_sent']
        metric.bytes_received = stats['bytes_received']
        metric.last_activity = stats['last_activity']
        metric.update_metrics()  # Recalculate derived metrics
        
    except Exception as e:
        ocpp_logger.warning(f"Error saving WS metric for station {station_id}: {e}")


# -------------------------
# Groups (single source of truth)
# -------------------------
UI_STATUS_GROUP = "stations_status"          # Browser UI websocket(s)
UI_HTML_GROUP = "charging_stations_group"    # Existing HTML partial updates (if you use it)


def _normalize_station_key(station_id: Union[int, str]) -> int:
    return int(station_id)


def register_station(station_id: Union[int, str], consumer) -> None:
    key = _normalize_station_key(station_id)
    station_runtime.set_online(key, consumer)
    ocpp_logger.info(f"Station {key} registered in station runtime service")


def unregister_station(station_id: Union[int, str]) -> None:
    key = _normalize_station_key(station_id)
    station_runtime.set_offline(key)
    for d in (_last_heartbeat_log, _last_heartbeat_db_update, _rapid_heartbeat_count):
        d.pop(key, None)
    
    # Finalize WebSocket performance metric when station disconnects
    _finalize_ws_metric(station_id)
    
    ocpp_logger.info(f"Station {key} unregistered from station runtime service")


def _finalize_ws_metric(station_id: Union[int, str]):
    """Finalize WebSocket metric when connection ends."""
    return


# -------------------------
# WebSocket wrapper for OCPP
# -------------------------
class WebSocketWrapper:
    def __init__(self, consumer: AsyncWebsocketConsumer):
        self.consumer = consumer
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, message: str) -> None:
        if not getattr(self.consumer, "_connected", False) or getattr(self.consumer, "_is_closing", False):
            return
        try:
            # Track WebSocket performance for sent messages
            try:
                st_id = getattr(self.consumer, "station_id", None)
                if st_id is not None:
                    track_ws_performance(st_id, len(message), 'sent')
            except Exception:
                pass
            
            await self.consumer.send(text_data=message)
        except RuntimeError:
            return

    async def recv(self) -> str:
        return await self.queue.get()

    async def feed(self, message: str) -> None:
        # Премахваме бързата ping/pong обработка
        await self.queue.put(message)


# -------------------------
# OCPP ChargePoint (Central System endpoint)
# -------------------------
class ChargePoint(OCPPChargePoint):
    """
    Rules enforced:
      - ACTIVE_STATIONS key is int station_id.
      - UI events always go to UI_STATUS_GROUP with JSON {type: ...}.
      - OCPP transactionId returned in StartTransaction is stored in Transaction.transaction_id.
      - All lookups from OCPP transactionId use Transaction.transaction_id (fallback to pk).
    """

    def __init__(self, station_id: Union[int, str], websocket: WebSocketWrapper, consumer):
        super().__init__(str(station_id), websocket)
        self.station_id: int = _normalize_station_key(station_id)

        self.consumer = consumer
        self.db_lock = asyncio.Lock()

        # optional: remember requested power for (connectorId, idTag) when RemoteStart includes profile
        self.pending_requested_power: Dict[Tuple[int, str], Optional[float]] = {}
        self.pending_session_context: Dict[Tuple[int, str], Dict[str, Any]] = {}

        self.last_seen = timezone.now()
        self.heartbeat_interval = int(_ocpp_station_configuration_defaults()["HeartbeatInterval"])
        self.charge_point_model: Optional[str] = None
        self.charge_point_vendor: Optional[str] = None

    def _log_ocpp_event(self, event_name: str, **fields: Any) -> None:
        rendered_fields = " ".join(
            f"{key}={value}"
            for key, value in fields.items()
            if value not in (None, "", [], {}, ())
        )
        get_station_logger(self.station_id).info(
            "%s:%s%s",
            event_name,
            " " if rendered_fields else "",
            rendered_fields,
        )

    def _serialize_ocpp_log_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {
                _snake_to_camel_case(str(key)): self._serialize_ocpp_log_value(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, (list, tuple, set)):
            return [self._serialize_ocpp_log_value(item) for item in value]
        if hasattr(value, "_asdict"):
            return self._serialize_ocpp_log_value(value._asdict())
        if hasattr(value, "__dict__"):
            return {
                _snake_to_camel_case(str(key)): self._serialize_ocpp_log_value(item)
                for key, item in vars(value).items()
                if not str(key).startswith("_") and item is not None
            }
        return str(value)

    def _format_ocpp_log_payload(self, payload: Any) -> str:
        serialized = self._serialize_ocpp_log_value(payload)
        if serialized in (None, ""):
            serialized = {}
        return json.dumps(serialized, ensure_ascii=True, sort_keys=True, default=str)

    def _log_ocpp_request(self, action_name: str, payload: Any, direction: str) -> None:
        station_logger = get_station_logger(self.station_id)
        if direction == "inbound":
            station_logger.info("Received %s request", action_name)
        else:
            station_logger.info("Sending %s request", action_name)
        station_logger.info("Request: %s", self._format_ocpp_log_payload(payload))

    def _log_ocpp_response(self, action_name: str, payload: Any, direction: str) -> None:
        station_logger = get_station_logger(self.station_id)
        if direction == "inbound":
            station_logger.info("Sending %s response", action_name)
        else:
            station_logger.info("%s response received", action_name)
        station_logger.info("Response: %s", self._format_ocpp_log_payload(payload))

    def _log_ocpp_response_error(self, action_name: str, exc: Exception, direction: str) -> None:
        error_payload = {
            "errorCode": getattr(exc, "code", exc.__class__.__name__),
            "errorDescription": getattr(exc, "description", str(exc)),
            "errorDetails": getattr(exc, "details", {}),
        }
        station_logger = get_station_logger(self.station_id)
        if direction == "inbound":
            station_logger.warning("Sending %s response error", action_name)
        else:
            station_logger.warning("%s response error received", action_name)
        station_logger.warning("ResponseError: %s", self._format_ocpp_log_payload(error_payload))

    async def _call_with_logging(self, action_name: str, request_payload: Any):
        self._log_ocpp_request(action_name, request_payload, direction="outbound")
        try:
            response = await self.call(request_payload)
        except ocpp_exceptions.OCPPError as exc:
            self._log_ocpp_response_error(action_name, exc, direction="outbound")
            raise
        except Exception:
            ocpp_logger.exception("%s outbound call failed", action_name)
            raise

        self._log_ocpp_response(action_name, response, direction="outbound")
        return response

    def _desired_station_configuration(self) -> Dict[str, str]:
        return _ocpp_station_configuration_defaults()

    def _configuration_map_from_response(self, response: Any) -> Dict[str, Dict[str, Any]]:
        config_map: Dict[str, Dict[str, Any]] = {}
        cfg_list = getattr(response, "configuration_key", None) if response else None
        if not isinstance(cfg_list, (list, tuple)):
            return config_map

        for item in cfg_list:
            key = getattr(item, "key", None)
            if not key:
                continue
            config_map[str(key)] = {
                "value": getattr(item, "value", None),
                "readonly": bool(getattr(item, "readonly", False)),
            }
        return config_map

    def _extract_vehicle_attributes(self, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}

        vehicle_payload = payload.get("vehicle") if isinstance(payload.get("vehicle"), dict) else payload
        battery_payload = payload.get("battery") if isinstance(payload.get("battery"), dict) else {}

        attrs: Dict[str, Any] = {}

        vin = vehicle_payload.get("vin") or payload.get("vin")
        registration_number = (
            vehicle_payload.get("registrationNumber")
            or vehicle_payload.get("registration_number")
            or payload.get("registrationNumber")
            or payload.get("licensePlate")
            or payload.get("plate")
        )
        manufacturer = (
            vehicle_payload.get("manufacturer")
            or vehicle_payload.get("make")
            or payload.get("manufacturer")
            or payload.get("make")
            or payload.get("brand")
        )
        model_name = (
            vehicle_payload.get("model")
            or vehicle_payload.get("modelName")
            or payload.get("vehicleModel")
            or payload.get("modelName")
        )
        model_year = (
            vehicle_payload.get("modelYear")
            or vehicle_payload.get("year")
            or payload.get("modelYear")
            or payload.get("year")
        )
        trim = (
            vehicle_payload.get("trim")
            or vehicle_payload.get("variant")
            or payload.get("trim")
            or payload.get("variant")
        )
        color = (
            vehicle_payload.get("color")
            or vehicle_payload.get("exteriorColor")
            or payload.get("color")
            or payload.get("exteriorColor")
        )
        battery_capacity_kwh = (
            battery_payload.get("capacityKwh")
            or vehicle_payload.get("batteryCapacityKwh")
            or payload.get("batteryCapacityKwh")
            or payload.get("battery_capacity_kwh")
        )
        last_known_soc_percent = (
            battery_payload.get("socPercent")
            or vehicle_payload.get("socPercent")
            or vehicle_payload.get("soc")
            or payload.get("socPercent")
            or payload.get("soc")
            or payload.get("batteryLevel")
        )

        if vin:
            attrs["vin"] = str(vin)[:64]
        if registration_number:
            attrs["registration_number"] = str(registration_number)[:32]
        if manufacturer:
            attrs["manufacturer"] = str(manufacturer)[:100]
        if model_name:
            attrs["model_name"] = str(model_name)[:100]
        if model_year not in (None, ""):
            try:
                attrs["model_year"] = int(model_year)
            except Exception:
                pass
        if trim:
            attrs["trim"] = str(trim)[:100]
        if color:
            attrs["color"] = str(color)[:50]
        if battery_capacity_kwh not in (None, ""):
            try:
                attrs["battery_capacity_kwh"] = Decimal(str(battery_capacity_kwh))
            except Exception:
                pass
        if last_known_soc_percent not in (None, ""):
            try:
                parsed_soc = float(last_known_soc_percent)
                if 0 <= parsed_soc <= 100:
                    attrs["last_known_soc_percent"] = parsed_soc
            except Exception:
                pass

        metadata: Dict[str, Any] = {}
        raw_metadata = payload.get("vehicleMetadata")
        if isinstance(raw_metadata, dict):
            metadata.update(raw_metadata)

        extra_metadata_map = {
            "estimated_range_km": (
                vehicle_payload.get("estimatedRangeKm")
                or payload.get("estimatedRangeKm")
                or payload.get("rangeKm")
            ),
            "battery_chemistry": battery_payload.get("chemistry") or payload.get("batteryChemistry"),
            "charge_port": vehicle_payload.get("chargePort") or payload.get("chargePort"),
            "odometer_km": vehicle_payload.get("odometerKm") or payload.get("odometerKm") or payload.get("odometer"),
        }
        for key, value in extra_metadata_map.items():
            if value not in (None, ""):
                metadata[key] = value

        if metadata:
            attrs["metadata"] = metadata

        return attrs

    def _upsert_vehicle(self, id_tag: str, payload: Optional[Dict[str, Any]] = None) -> Optional[Vehicle]:
        normalized_identifier = (id_tag or "").strip()[:64]
        if not normalized_identifier:
            return None

        attrs = self._extract_vehicle_attributes(payload)
        now = timezone.now()
        defaults = {**attrs, "last_seen_at": now}

        vehicle, _ = Vehicle.objects.get_or_create(
            vehicle_identifier=normalized_identifier,
            defaults=defaults,
        )

        changed_fields = []
        if vehicle.last_seen_at != now:
            vehicle.last_seen_at = now
            changed_fields.append("last_seen_at")

        for field_name, field_value in attrs.items():
            if field_name == "metadata":
                if field_value and field_value != vehicle.metadata:
                    merged_metadata = dict(vehicle.metadata or {})
                    merged_metadata.update(field_value)
                    vehicle.metadata = merged_metadata
                    changed_fields.append("metadata")
                continue

            if field_value not in (None, "") and getattr(vehicle, field_name) != field_value:
                setattr(vehicle, field_name, field_value)
                changed_fields.append(field_name)

        if changed_fields:
            vehicle.save(update_fields=list(dict.fromkeys(changed_fields)))

        return vehicle

    @database_sync_to_async
    def _update_active_vehicle_from_payload(self, payload: Dict[str, Any]) -> bool:
        active_tx = (
            Transaction.objects
            .filter(connector__station_id=self.station_id, status="active")
            .select_related("vehicle")
            .order_by("-started_at", "-id")
            .first()
        )
        if not active_tx:
            return False

        vehicle = self._upsert_vehicle(active_tx.id_tag, payload)
        if vehicle and active_tx.vehicle_id != vehicle.id:
            active_tx.vehicle = vehicle
            active_tx.save(update_fields=["vehicle"])
        return vehicle is not None

    def _update_vehicle_soc(self, vehicle: Optional[Vehicle], soc_value: Optional[float], observed_at=None) -> None:
        if not vehicle or soc_value is None:
            return

        update_fields = ["last_seen_at"]
        vehicle.last_seen_at = observed_at or timezone.now()
        if vehicle.last_known_soc_percent != soc_value:
            vehicle.last_known_soc_percent = soc_value
            update_fields.append("last_known_soc_percent")
        vehicle.save(update_fields=update_fields)

    def _resolve_pending_remote_start(
        self,
        connector_id: int,
        id_tag: str,
    ) -> tuple[Optional[Tuple[int, str]], Optional[float], Dict[str, Any]]:
        normalized_id_tag = (id_tag or "")[:20]
        exact_key = (int(connector_id), normalized_id_tag)
        if exact_key in self.pending_requested_power or exact_key in self.pending_session_context:
            return (
                exact_key,
                self.pending_requested_power.get(exact_key),
                dict(self.pending_session_context.get(exact_key, {})),
            )

        connector_candidates = {
            key for key in self.pending_requested_power.keys() if key[0] == int(connector_id)
        } | {
            key for key in self.pending_session_context.keys() if key[0] == int(connector_id)
        }

        if len(connector_candidates) != 1:
            return None, None, {}

        matched_key = next(iter(connector_candidates))
        if matched_key[1] != normalized_id_tag:
            ocpp_logger.warning(
                "StartTransaction idTag mismatch for station=%s connector=%s: station sent %s, pending remote start used %s",
                self.station_id,
                connector_id,
                normalized_id_tag,
                matched_key[1],
            )

        return (
            matched_key,
            self.pending_requested_power.get(matched_key),
            dict(self.pending_session_context.get(matched_key, {})),
        )


    async def route_message(self, raw_msg: str):
        self.last_seen = timezone.now()
        try:
            return await super().route_message(raw_msg)
        except Exception as e:
            s = str(e)
            if (
                "Payload for Action is incomplete" in s
                or "missing 2 required positional arguments" in s
                or "doesn't seem to be valid OCPP" in s
            ):
                ocpp_logger.warning(f"Ignoring malformed message from station/simulator: {raw_msg}")
                return
            raise

    # -------------------------
    # DB helpers
    # -------------------------
    @database_sync_to_async
    def update_station_model(self, station_id: int, model: str, vendor: Optional[str] = None) -> bool:
        try:
            st = Station.objects.filter(id=station_id).first()
            if not st:
                return False
            update_fields = []
            if getattr(st, "model", None) in (None, ""):
                st.model = model
                update_fields.append("model")
            # keep existing behavior: vendor -> connector_type (if you rely on it)
            if vendor and getattr(st, "connector_type", None) in (None, ""):
                st.connector_type = vendor
                update_fields.append("connector_type")
            if update_fields:
                st.save(update_fields=update_fields)
            return True
        except Exception:
            ocpp_logger.exception("Error updating station model")
            return False

    @database_sync_to_async
    def _touch_station_last_seen(self) -> None:
        Station.objects.filter(id=self.station_id).update(last_seen=timezone.now())

    async def _update_station_status_async(self, status: str, reason: str = "") -> bool:
        station_id = self.station_id

        @database_sync_to_async
        def update_db() -> bool:
            with db_transaction.atomic():
                st = Station.objects.select_for_update().filter(id=station_id).first()
                if not st:
                    return False
                changed = (st.status != status)
                st.status = status
                st.last_seen = timezone.now()
                st.save(update_fields=["status", "last_seen"])
                return changed

        try:
            changed = await update_db()
        except Exception:
            ocpp_logger.exception("Error updating station status in DB")
            return False

        if changed and getattr(self, "consumer", None):
            try:
                await self.consumer.broadcast_station_status(station_id, status=status, reason=reason)
            except Exception:
                ocpp_logger.exception("Error broadcasting station status update")

        return changed

    @database_sync_to_async
    def _batch_create_connectors(self, num_connectors: int) -> None:
        existing = set(
            Connector.objects.filter(station_id=self.station_id)
            .values_list("connector_id", flat=True)
        )
        new = [
            Connector(station_id=self.station_id, connector_id=cid, status="available")
            for cid in range(1, num_connectors + 1)
            if cid not in existing
        ]
        if new:
            Connector.objects.bulk_create(new)

    async def _post_boot_setup(self) -> None:
        consumer = getattr(self, "consumer", None)
        if not consumer or not getattr(consumer, "_connected", False):
            return

        desired_configuration = self._desired_station_configuration()
        requested_keys = ["NumberOfConnectors", *desired_configuration.keys()]
        config = None
        try:
            config = await asyncio.wait_for(
                self.call_get_configuration(keys=requested_keys),
                timeout=_ocpp_configuration_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            ocpp_logger.warning("GetConfiguration timeout (non-critical)")
        except Exception:
            ocpp_logger.exception("GetConfiguration failed (non-critical)")

        num_connectors = 1
        configuration_map = self._configuration_map_from_response(config)
        try:
            if "NumberOfConnectors" in configuration_map:
                num_connectors = max(1, int(configuration_map["NumberOfConnectors"]["value"] or 1))
        except Exception:
            ocpp_logger.exception("Failed to parse NumberOfConnectors; using default 1")

        self._log_ocpp_event(
            "GetConfiguration",
            requested_keys=",".join(requested_keys),
            number_of_connectors=num_connectors,
            meter_value_sample_interval=configuration_map.get("MeterValueSampleInterval", {}).get("value"),
            clock_aligned_data_interval=configuration_map.get("ClockAlignedDataInterval", {}).get("value"),
        )

        for key, desired_value in desired_configuration.items():
            current_entry = configuration_map.get(key, {})
            current_value = current_entry.get("value")
            is_readonly = bool(current_entry.get("readonly", False))
            if str(current_value) == str(desired_value):
                self._log_ocpp_event("ChangeConfiguration", key=key, result="unchanged", value=current_value)
                continue
            if is_readonly:
                self._log_ocpp_event(
                    "ChangeConfiguration",
                    key=key,
                    result="readonly",
                    current_value=current_value,
                    desired_value=desired_value,
                )
                continue

            try:
                response = await asyncio.wait_for(
                    self.call_change_configuration(key=key, value=str(desired_value)),
                    timeout=_ocpp_configuration_timeout_seconds(),
                )
                result_status = getattr(response, "status", None)
                if hasattr(result_status, "value"):
                    result_status = result_status.value
                self._log_ocpp_event(
                    "ChangeConfiguration",
                    key=key,
                    result=result_status or "unknown",
                    desired_value=desired_value,
                    previous_value=current_value,
                )
            except asyncio.TimeoutError:
                self._log_ocpp_event(
                    "ChangeConfiguration",
                    key=key,
                    result="timeout",
                    desired_value=desired_value,
                    previous_value=current_value,
                )
            except ocpp_exceptions.OCPPError as exc:
                error_code = getattr(exc, "code", exc.__class__.__name__)
                self._log_ocpp_event(
                    "ChangeConfiguration",
                    key=key,
                    result="call_error",
                    error_code=error_code,
                    desired_value=desired_value,
                    previous_value=current_value,
                )
            except Exception:
                ocpp_logger.exception("ChangeConfiguration failed for %s", key)

        try:
            await self._batch_create_connectors(num_connectors)
        except Exception:
            ocpp_logger.exception("Failed to batch create connectors (non-critical)")

        for cid in range(1, num_connectors + 1):
            try:
                await consumer.broadcast_connector_status(self.station_id, "available", cid)
            except Exception:
                ocpp_logger.exception("Failed to broadcast connector status")


    # -------------------------
    # OCPP 1.6J handlers
    # -------------------------
    @on(Action.BootNotification)
    async def on_boot_notification(self, charge_point_vendor: str, charge_point_model: str, **kwargs):
        self.charge_point_model = charge_point_model
        self.charge_point_vendor = charge_point_vendor

        firmware_version = kwargs.get("firmware_version") or kwargs.get("firmwareVersion")
        self._log_ocpp_request(
            "BootNotification",
            {
                "chargePointVendor": charge_point_vendor,
                "chargePointModel": charge_point_model,
                "firmwareVersion": firmware_version,
                "chargeBoxSerialNumber": kwargs.get("charge_box_serial_number") or kwargs.get("chargeBoxSerialNumber"),
            },
            direction="inbound",
        )

        station_id = self.station_id
        self.heartbeat_interval = int(
            getattr(
                self,
                "default_heartbeat_interval",
                int(_ocpp_station_configuration_defaults()["HeartbeatInterval"]),
            )
        )

        @database_sync_to_async
        def check_station_exists():
            return Station.objects.filter(id=station_id).exists()

        try:
            station_exists = await check_station_exists()
        except Exception:
            ocpp_logger.exception("Error validating station existence")
            station_exists = False

        if not station_exists:
            get_station_logger(self.station_id).warning(
                "BootNotification rejected: Station %s not found in database.",
                station_id,
            )
            current_time = (
                timezone.now()
                .astimezone(py_datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            response = call_result.BootNotificationPayload(
                status=RegistrationStatus.rejected,
                current_time=current_time,
                interval=self.heartbeat_interval,
            )
            self._log_ocpp_response("BootNotification", response, direction="inbound")
            return response

        self._log_ocpp_event(
            "BootNotification",
            station_id=station_id,
            vendor=charge_point_vendor,
            model=charge_point_model,
            firmware=firmware_version,
            heartbeat_interval_seconds=self.heartbeat_interval,
        )

        try:
            asyncio.create_task(self._update_station_status_async("active", "boot"))
            asyncio.create_task(self._post_boot_setup())
            asyncio.create_task(self.update_station_model(station_id, charge_point_model, charge_point_vendor))
        except Exception:
            ocpp_logger.exception("BootNotification background task error")

        current_time = (
            timezone.now()
            .astimezone(py_datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        response = call_result.BootNotificationPayload(
            status=RegistrationStatus.accepted,
            current_time=current_time,
            interval=self.heartbeat_interval,
        )
        self._log_ocpp_response("BootNotification", response, direction="inbound")
        return response

    @on(Action.Authorize)
    async def on_authorize(self, id_tag: str, **kwargs):
        id_tag = (id_tag or "")[:20]
        self._log_ocpp_request(
            "Authorize",
            {"idTag": id_tag},
            direction="inbound",
        )

        try:
            is_valid = await database_sync_to_async(
                lambda: UserRFID.objects.filter(
                    tag=id_tag,
                    stations__id=self.station_id,  # station_id is already normalized to int (PK)
                    is_active=True,
                ).exists()
            )()
        except Exception:
            ocpp_logger.exception("Error checking RFID")
            is_valid = False

        if is_valid:
            status = AuthorizationStatus.accepted.value
        else:
            status = AuthorizationStatus.invalid.value

        if is_valid and getattr(self, "consumer", None):
            try:
                await self.consumer.broadcast_authorization_success(self.station_id, id_tag)
            except Exception:
                ocpp_logger.exception("Error broadcasting authorization success")

        response = call_result.AuthorizePayload(id_tag_info={"status": status})
        self._log_ocpp_response("Authorize", response, direction="inbound")
        return response

    @on(Action.StatusNotification)
    async def on_status_notification(self, connector_id: int, error_code: str, status: str, **kwargs):
        self.last_seen = timezone.now()
        station_id = self.station_id
        self._log_ocpp_request(
            "StatusNotification",
            {
                "connectorId": int(connector_id),
                "status": status,
                "errorCode": error_code,
                "info": kwargs.get("info"),
                "timestamp": kwargs.get("timestamp"),
            },
            direction="inbound",
        )
        def normalize_status(s: str) -> str:
            s_lower = (s or "").strip().lower()
            mapping = {
                "available": "available",
                "preparing": "preparing",
                "charging": "charging",
                "suspendedevse": "suspendedEVSE",
                "suspendedev": "suspendedEV",
                "finishing": "finishing",
                "reserved": "reserved",
                "faulted": "faulted",
                "unavailable": "offline",
            }
            return mapping.get(s_lower, "available")

        normalized = normalize_status(status)

        self._log_ocpp_event(
            "StatusNotification",
            station_id=station_id,
            connector_id=connector_id,
            status=status,
            normalized_status=normalized,
            error_code=error_code,
        )

        # connectorId=0 is station-level state
        if int(connector_id) == 0:
            s = (status or "").strip().lower()
            try:
                if s == "available":
                    asyncio.create_task(self._update_station_status_async("active", "status0"))
                elif s in {"faulted", "unavailable"}:
                    asyncio.create_task(self._update_station_status_async("inactive", "status0"))
                    
                # Update last status on Station model
                @database_sync_to_async
                def update_station_last_status():
                    st = Station.objects.filter(id=station_id).first()
                    if st:
                        st.last_status = s
                        st.save(update_fields=['last_status'])
                asyncio.create_task(update_station_last_status())
            except Exception:
                ocpp_logger.exception("Failed scheduling station status update for connectorId=0")
            response = call_result.StatusNotificationPayload()
            self._log_ocpp_response("StatusNotification", response, direction="inbound")
            return response

        try:
            async with self.db_lock:

                @database_sync_to_async
                def upsert_connector():
                    # Use update_or_create to avoid unique_together integrity errors under load
                    conn, created = Connector.objects.update_or_create(
                        station_id=station_id,
                        connector_id=int(connector_id),
                        defaults={"status": normalized},
                    )
                    changed = False
                    # We don't have the old status nicely with update_or_create unless we fetch first, 
                    # but it's okay because we are saving it anyway. 
                    # For consistency, we'll just return True for change if it was created.
                    return conn.id, created, created, normalized

                connector_pk, created, changed, old = await upsert_connector()

                # reconcile active tx if connector ends or faults
                if normalized in {"available", "faulted", "offline"}:

                    @database_sync_to_async
                    def reconcile_tx():
                        conn = Connector.objects.get(pk=connector_pk)
                        tx = (
                            Transaction.objects
                            .filter(connector=conn, status="active")
                            .order_by("-started_at", "-id")
                            .first()
                        )
                        if not tx:
                            return None

                        last_mv = (
                            MeterValue.objects
                            .filter(transaction=tx)
                            .order_by("-timestamp", "-id")
                            .first()
                        )
                        if last_mv and last_mv.value is not None:
                            tx.meter_stop = last_mv.value

                        tx.stopped_at = timezone.now()
                        tx.status = "completed" if normalized == "available" else "error"
                        tx.save(update_fields=["meter_stop", "stopped_at", "status"])
                        return tx.transaction_id or tx.id

                    finalized = await reconcile_tx()
                    if finalized:
                        get_station_logger(self.station_id).warning(f"Reconciled transaction {finalized} due to connector status {status}")

                asyncio.create_task(self._update_station_status_async("active", "status"))

                consumer = getattr(self, "consumer", None)
                if consumer:
                    await consumer.broadcast_connector_status(station_id, normalized, int(connector_id))

        except Exception:
            ocpp_logger.exception("Error processing StatusNotification")

        response = call_result.StatusNotificationPayload()
        self._log_ocpp_response("StatusNotification", response, direction="inbound")
        return response

    @on(Action.Heartbeat)
    async def on_heartbeat(self):
        self.last_seen = timezone.now()
        station_id = self.station_id
        station_logger = get_station_logger(self.station_id)

        # Uses Django cache (Redis ideally) instead of global mem structures to support multiple workers
        from django.core.cache import cache
        LOG_THROTTLE = 60
        DB_UPDATE_THROTTLE = 15
        RAPID_COUNT_LIMIT = 10

        now_ts = timezone.now()
        now_ts_sec = now_ts.timestamp()
        
        last_log_key = f"hb_log_{station_id}"
        last_db_key = f"hb_db_{station_id}"
        rapid_count_key = f"hb_counts_{station_id}"
        rapid_window_key = f"hb_window_{station_id}"

        last_log = cache.get(last_log_key)
        should_log_heartbeat = not last_log or (now_ts_sec - last_log) >= LOG_THROTTLE
        if should_log_heartbeat:
            self._log_ocpp_request("Heartbeat", {}, direction="inbound")
        if not last_log or (now_ts_sec - last_log) >= LOG_THROTTLE:
            self._log_ocpp_event("Heartbeat", station_id=station_id, action="received")
            cache.set(last_log_key, now_ts_sec, timeout=LOG_THROTTLE*2)

        last_db = cache.get(last_db_key)
        if not last_db or (now_ts_sec - last_db) >= DB_UPDATE_THROTTLE:
            cache.set(last_db_key, now_ts_sec, timeout=DB_UPDATE_THROTTLE*2)
            try:
                await self._touch_station_last_seen()
            except Exception:
                ocpp_logger.exception("Failed updating station last_seen")

        window_start = cache.get(rapid_window_key) or now_ts_sec
        count = cache.get(rapid_count_key) or 0
        if (now_ts_sec - window_start) < LOG_THROTTLE:
            count += 1
            cache.set(rapid_count_key, count, timeout=LOG_THROTTLE*2)
            cache.set(rapid_window_key, window_start, timeout=LOG_THROTTLE*2)
        else:
            cache.set(rapid_count_key, 1, timeout=LOG_THROTTLE*2)
            cache.set(rapid_window_key, now_ts_sec, timeout=LOG_THROTTLE*2)
            count = 1

        if count > RAPID_COUNT_LIMIT:
            get_station_logger(self.station_id).warning(f"Rapid heartbeats detected ({count} in {LOG_THROTTLE}s)")

        current_time = (
            now_ts.astimezone(py_datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        response = call_result.HeartbeatPayload(current_time=current_time)
        if should_log_heartbeat:
            self._log_ocpp_response("Heartbeat", response, direction="inbound")
        return response


    @on(Action.MeterValues)
    async def on_meter_values(
        self,
        connector_id: int,
        meter_value,
        transaction_id: Optional[int] = None,
        **kwargs,
    ):
        self.last_seen = timezone.now()
        self._log_ocpp_request(
            "MeterValues",
            {
                "connectorId": int(connector_id),
                "transactionId": transaction_id,
                "meterValue": meter_value or [],
            },
            direction="inbound",
        )

        soc_percentage: Optional[float] = None
        soc_timestamp: Optional[str] = None
        soc_source: Optional[str] = None

        # ---------------------------
        # Define vendor-specific measurands
        # ---------------------------
        vendor_soc_fields = ["BatterySOC", "BatteryLevel", "SOCPercent"]  # ABB or other vendors

        # ---------------------------
        # Parse SoC safely
        # ---------------------------
        try:
            for mv in meter_value or []:
                parent_ts = mv.get("timestamp")

                for sv in (mv.get("sampled_value") or []):
                    measurand = sv.get("measurand")
                    unit = sv.get("unit")
                    value = sv.get("value")

                    if measurand in ("SoC", "StateOfCharge", "soc") or measurand in vendor_soc_fields:
                        if unit not in (None, "Percent", "%"):
                            continue

                        try:
                            parsed = float(value)
                            # Convert fraction to percent if necessary
                            if parsed <= 1:
                                parsed *= 100
                        except (TypeError, ValueError):
                            continue

                        # sanity bounds
                        if 0 <= parsed <= 100:
                            soc_percentage = parsed
                            soc_timestamp = parent_ts
                            soc_source = "iso15118" if measurand in ("SoC", "StateOfCharge", "soc") else "vendor"
                            break

                if soc_percentage is not None:
                    break

        except Exception:
            ocpp_logger.exception("Failed parsing SoC from MeterValues")

        if not transaction_id:
            response = call_result.MeterValuesPayload()
            self._log_ocpp_response("MeterValues", response, direction="inbound")
            return response

        # ---------------------------
        # Persist safely
        # ---------------------------
        async with self.db_lock:

            @database_sync_to_async
            def persist():
                tx = (
                    Transaction.objects
                    .filter(transaction_id=int(transaction_id))
                    .first()
                )

                if not tx:
                    tx = Transaction.objects.filter(id=int(transaction_id)).first()

                if not tx:
                    tx = (
                        Transaction.objects
                        .filter(
                            connector__station_id=self.station_id,
                            status="active",
                        )
                        .order_by("-started_at", "-id")
                        .first()
                    )
                    
                    if not tx:
                        # Fallback for meter values arriving just after stop transaction
                        five_mins_ago = timezone.now() - py_datetime.timedelta(minutes=5)
                        tx = (
                            Transaction.objects
                            .filter(
                                connector__station_id=self.station_id,
                                status="completed",
                                stopped_at__gte=five_mins_ago
                            )
                            .order_by("-stopped_at", "-id")
                            .first()
                        )

                    if not tx:
                        return None

                # Create a new MeterValue per reading
                # Extract the latest values from the payload
                energy_wh = None
                power_w = None
                
                for mv in meter_value or []:
                    # Attempt to extract Energy.Active.Import.Register (Wh) and Power.Active.Import (W)
                    for sv in (mv.get("sampled_value") or []):
                        measurand = sv.get("measurand", "Energy.Active.Import.Register")
                        val = sv.get("value")
                        if not val:
                            continue
                            
                        try:
                            num_val = float(val)
                            
                            # Usually Energy is standard Wh but can be kWh
                            if measurand == "Energy.Active.Import.Register":
                                if sv.get("unit") == "kWh":
                                    num_val *= 1000
                                energy_wh = round(num_val)  # handles large decimal numbers seamlessly 
                                
                            # Usually Power is standard W but can be kW
                            elif measurand == "Power.Active.Import":
                                if sv.get("unit") == "kW":
                                    num_val *= 1000
                                power_w = round(num_val)
                        except (ValueError, TypeError):
                            pass

                # Store raw payload just in case
                previous_session_context = {}
                latest_meter = MeterValue.objects.filter(transaction=tx).order_by('-timestamp', '-id').first()
                if latest_meter and isinstance(latest_meter.data, dict):
                    previous_session_context = latest_meter.data.get('session_context', {}) or {}

                data_dict = {
                    "raw_payload": [mv_dict for mv_dict in (meter_value or [])],
                    "session_context": previous_session_context,
                }

                # Send signals for processing
                from renew_website.apps.charging_stations.tasks import process_meter_values
                # We can call process_meter_values task (delaying it or locally)
                try:
                    process_meter_values.delay(
                        station_id=self.station_id,
                        connector_id=connector_id,
                        transaction_id=tx.id,
                        power_w=power_w or 0,
                        energy_wh=energy_wh or 0,
                        soc_percentage=soc_percentage,
                        mv_data=data_dict
                    )
                except Exception as e:
                    ocpp_logger.warning(f"Could not trigger process_meter_values: {e}")

                return {
                    "station_id": self.station_id,
                    "soc_percentage": soc_percentage,
                    "power_w": power_w,
                    "energy_wh": energy_wh,
                }

            result = await persist()

        self._log_ocpp_event(
            "MeterValues",
            station_id=self.station_id,
            connector_id=connector_id,
            transaction_id=transaction_id,
            power_w=result.get("power_w") if result else None,
            energy_wh=result.get("energy_wh") if result else None,
            soc_percentage=round(soc_percentage, 2) if soc_percentage is not None else None,
            sample_count=sum(len((mv.get("sampled_value") or [])) for mv in (meter_value or [])),
        )

        # ---------------------------
        # Broadcast SoC update
        # ---------------------------
        if (
            result
            and result.get("soc_percentage") is not None
            and getattr(self, "consumer", None)
        ):
            try:
                await self.consumer.broadcast_soc_update(
                    self.station_id,
                    float(result["soc_percentage"]),
                )
            except Exception:
                ocpp_logger.exception("Failed broadcasting SoC update")

        response = call_result.MeterValuesPayload()
        self._log_ocpp_response("MeterValues", response, direction="inbound")
        return response


    @on(Action.DataTransfer)
    async def on_data_transfer(self, vendor_id: str, message_id: Optional[str] = None, data: Optional[str] = None, **kwargs):
        """
        Supports:
          - Generic / SoCData: data is JSON string {"soc": <num>, "timestamp": "<iso>"}
                    - Vendor telemetry snapshots that carry SoC outside standard MeterValues
        """
        self._log_ocpp_request(
            "DataTransfer",
            {
                "vendorId": vendor_id,
                "messageId": message_id,
                "data": data,
            },
            direction="inbound",
        )
        # Generic SoCData (your simulator)
        if (vendor_id or "") == "Generic" and (message_id or "") == "SoCData" and data:
            try:
                payload = json.loads(data) if isinstance(data, str) else data
                soc_raw = payload.get("soc")
                if soc_raw is not None:
                    soc_value = float(soc_raw)

                    ts = None
                    ts_raw = payload.get("timestamp")
                    if ts_raw:
                        try:
                            ts = timezone.datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                        except Exception:
                            ts = None
                    ts = ts or timezone.now()

                    await self._persist_soc_from_vendor(soc_value, ts, source="vendor:generic")
                    if getattr(self, "consumer", None):
                        await self.consumer.broadcast_soc_update(self.station_id, soc_value)
            except Exception:
                ocpp_logger.exception("Error processing Generic SoCData")
            response = call_result.DataTransferPayload(status="Accepted")
            self._log_ocpp_response("DataTransfer", response, direction="inbound")
            return response

        parsed_payload = None
        if data:
            try:
                parsed_payload = json.loads(data) if isinstance(data, str) else data
            except Exception:
                parsed_payload = None

        if isinstance(parsed_payload, dict):
            try:
                await self._update_active_vehicle_from_payload(parsed_payload)
            except Exception:
                ocpp_logger.exception("Error updating vehicle metadata from DataTransfer")

        try:
            soc_data = self.parse_vendor_soc_data(parsed_payload if isinstance(parsed_payload, dict) else data, vendor_id)
            if soc_data:
                await self.process_vendor_soc(soc_data)
                self._log_ocpp_event(
                    "VendorSoC",
                    station_id=self.station_id,
                    vendor_id=vendor_id,
                    message_id=message_id,
                    soc_percentage=round(float(soc_data.get("percentage")), 2) if soc_data.get("percentage") is not None else None,
                )
        except Exception:
            ocpp_logger.exception("Error processing vendor DataTransfer")

        response = call_result.DataTransferPayload(status="Accepted")
        self._log_ocpp_response("DataTransfer", response, direction="inbound")
        return response

    @database_sync_to_async
    def _persist_soc_from_vendor(self, soc_value: float, ts, source: str) -> None:
        tx = (
            Transaction.objects
            .filter(connector__station_id=self.station_id, status="active")
            .order_by("-started_at", "-id")
            .first()
        )
        if not tx:
            return

        MeterValue.objects.create(
            transaction=tx,
            value=tx.meter_start,
            soc_percentage=float(soc_value),
            timestamp=ts,
            data={
                "soc_percentage": float(soc_value),
                "soc_timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                "soc_source": source,
                "samples": []
            },
        )
        self._update_vehicle_soc(tx.vehicle, float(soc_value), observed_at=ts)

    @on(Action.DiagnosticsStatusNotification)
    async def on_diagnostics_status_notification(self, status: str, **kwargs):
        self._log_ocpp_request(
            "DiagnosticsStatusNotification",
            {"status": status},
            direction="inbound",
        )
        ocpp_logger.info(f"DiagnosticsStatusNotification: station={self.station_id} status={status}")
        response = call_result.DiagnosticsStatusNotificationPayload()
        self._log_ocpp_response("DiagnosticsStatusNotification", response, direction="inbound")
        return response

    @on(Action.FirmwareStatusNotification)
    async def on_firmware_status_notification(self, status: str, **kwargs):
        self._log_ocpp_request(
            "FirmwareStatusNotification",
            {"status": status},
            direction="inbound",
        )
        self._log_ocpp_event(
            "FirmwareStatusNotification",
            station_id=self.station_id,
            status=status,
        )
        response = call_result.FirmwareStatusNotificationPayload()
        self._log_ocpp_response("FirmwareStatusNotification", response, direction="inbound")
        return response

    @on(Action.SecurityEventNotification)
    async def on_security_event_notification(self, type: str, timestamp: str, **kwargs):
        self._log_ocpp_request(
            "SecurityEventNotification",
            {
                "type": type,
                "timestamp": timestamp,
                "techInfo": kwargs.get("techInfo"),
            },
            direction="inbound",
        )
        try:
            get_station_logger(self.station_id).info(
                "SecurityEventNotification: station=%s type=%s timestamp=%s techInfo=%s",
                self.station_id,
                type,
                timestamp,
                kwargs.get("techInfo"),
            )
        except Exception:
            pass
        response = call_result.SecurityEventNotificationPayload()
        self._log_ocpp_response("SecurityEventNotification", response, direction="inbound")
        return response

    @on(Action.StartTransaction)
    async def on_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        timestamp: str,
        meter_start: int,
        reservation_id: Optional[int] = None,
        **kwargs,
    ):
        id_tag = (id_tag or "")[:20]
        self._log_ocpp_request(
            "StartTransaction",
            {
                "connectorId": int(connector_id),
                "idTag": id_tag,
                "timestamp": str(timestamp),
                "meterStart": meter_start,
                "reservationId": reservation_id,
            },
            direction="inbound",
        )

        pending_key, requested_power, session_context = self._resolve_pending_remote_start(
            int(connector_id),
            id_tag,
        )

        # Заявка от платформата? Ако да, автоматично одобряваме,
        #  без да изискваме RFID чекиране.
        is_remote_start = pending_key is not None

        if is_remote_start:
            is_valid = True
        else:
            try:
                is_valid = await database_sync_to_async(
                    lambda: UserRFID.objects.filter(
                        tag=id_tag,
                        stations__id=self.station_id,
                        is_active=True,
                    ).exists()
                )()
            except Exception:
                ocpp_logger.exception("RFID validation error")
                is_valid = False

        if not is_valid:
            response = call_result.StartTransactionPayload(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid.value},
            )
            self._log_ocpp_response("StartTransaction", response, direction="inbound")
            return response

        async with self.db_lock:

            @database_sync_to_async
            def create_tx():
                with db_transaction.atomic():
                    conn, _ = Connector.objects.get_or_create(
                        station_id=self.station_id,
                        connector_id=int(connector_id),
                        defaults={"status": "available"},
                    )

                    vehicle = self._upsert_vehicle(id_tag, kwargs)

                    tx = Transaction.objects.create(
                        connector=conn,
                        vehicle=vehicle,
                        id_tag=id_tag,
                        meter_start=meter_start,
                        requested_power_kw=requested_power,
                        status="active",
                    )

                    # OCPP transactionId == returned transaction_id; store into tx.transaction_id
                    if hasattr(tx, "transaction_id"):
                        tx.transaction_id = int(tx.id)
                        tx.save(update_fields=["transaction_id"])
                    else:
                        tx_id_used = tx.id

                    MeterValue.objects.get_or_create(
                        transaction=tx,
                        defaults={
                            "value": meter_start,
                            "data": {
                                "start": {"ocpp_timestamp": str(timestamp), "meter_start": meter_start},
                                "session_context": session_context,
                                "samples": [],
                            },
                        },
                    )

                    conn.status = "charging"
                    conn.save(update_fields=["status"])

                    return int(getattr(tx, "transaction_id", tx.id))

            tx_pk = await create_tx()

        if pending_key is not None:
            self.pending_requested_power.pop(pending_key, None)
            self.pending_session_context.pop(pending_key, None)

        try:
            asyncio.create_task(self._update_station_status_async("active", "start"))
        except Exception:
            pass

        if getattr(self, "consumer", None):
            try:
                await self.consumer.broadcast_connector_status(self.station_id, "charging", int(connector_id))
            except Exception:
                ocpp_logger.exception("Failed broadcasting connector charging status")

        # Return OCPP transactionId (we use DB pk)
        response = call_result.StartTransactionPayload(
            transaction_id=int(tx_pk),
            id_tag_info={"status": AuthorizationStatus.accepted.value},
        )
        self._log_ocpp_response("StartTransaction", response, direction="inbound")
        return response

    @on(Action.StopTransaction)
    async def on_stop_transaction(
        self,
        transaction_id: int,
        timestamp: str,
        meter_stop: int,
        id_tag: Optional[str] = None,
        reason: Optional[str] = None,
        transaction_data: Optional[list] = None,
        **kwargs,
    ):
        self._log_ocpp_request(
            "StopTransaction",
            {
                "transactionId": int(transaction_id),
                "timestamp": str(timestamp),
                "meterStop": meter_stop,
                "idTag": id_tag,
                "reason": reason,
                "transactionData": transaction_data,
            },
            direction="inbound",
        )
        valid_reasons = {
            "EmergencyStop", "EVDisconnected", "HardReset", "Local", "Other", "PowerLoss",
            "Reboot", "Remote", "SoftReset", "UnlockCommand", "DeAuthorized",
        }
        safe_reason = reason if reason in valid_reasons else "Other"

        async with self.db_lock:

            @database_sync_to_async
            def stop_tx():
                with db_transaction.atomic():
                    # transaction_id here is OCPP transactionId
                    tx = (
                        Transaction.objects
                        .select_related("connector")
                        .select_for_update()
                        .filter(transaction_id=int(transaction_id))
                        .first()
                    )
                    if not tx:
                        tx = (
                            Transaction.objects
                            .select_related("connector")
                            .select_for_update()
                            .filter(id=int(transaction_id))
                            .first()
                        )
                    if not tx:
                        return None
                        
                    # Fix Meter Value units scaling discrepancy
                    normalized_meter_stop = meter_stop
                    if tx.meter_start is not None and meter_stop is not None:
                        # Ex: meter_start is 54000 (Wh), meter_stop is 54 (kWh) -> multiplier needed
                        if meter_stop > 0 and (tx.meter_start / meter_stop) > 100:
                            normalized_meter_stop = meter_stop * 1000
                            ocpp_logger.warning(f"Normalized meter_stop for TX {tx.id} from {meter_stop} to {normalized_meter_stop}")

                    tx.meter_stop = normalized_meter_stop
                    tx.stopped_at = timezone.now()
                    tx.status = "completed"
                    tx.save(update_fields=["meter_stop", "stopped_at", "status"])

                    conn = tx.connector
                    if conn:
                        conn.status = "available"
                        conn.save(update_fields=["status"])

                    try:
                        latest_meter = MeterValue.objects.filter(transaction=tx).order_by('-timestamp', '-id').first()
                        previous_session_context = {}
                        if latest_meter and isinstance(latest_meter.data, dict):
                            previous_session_context = latest_meter.data.get("session_context", {}) or {}

                        MeterValue.objects.create(
                            transaction=tx,
                            value=normalized_meter_stop,
                            data={
                                "type": "final",
                                "ocpp_timestamp": str(timestamp),
                                "meter_start": tx.meter_start,
                                "meter_stop": normalized_meter_stop,
                                "reason": safe_reason,
                                "session_context": previous_session_context,
                            },
                        )
                    except Exception:
                        pass

                    return int(conn.connector_id) if conn else None

            conn_id = await stop_tx()

        if getattr(self, "consumer", None) and conn_id:
            try:
                await self.consumer.broadcast_connector_status(self.station_id, "available", int(conn_id))
            except Exception:
                ocpp_logger.exception("Failed broadcasting connector available status")

        response = call_result.StopTransactionPayload(
            id_tag_info={"status": AuthorizationStatus.accepted.value}
        )
        self._log_ocpp_response("StopTransaction", response, direction="inbound")
        return response

    # -------------------------
    # Vendor SoC helpers (internal only)
    # -------------------------
    def parse_vendor_soc_data(self, data: Union[str, dict], vendor_id: str):
        try:
            payload = data
            if isinstance(data, str):
                payload = json.loads(data)
            if not isinstance(payload, dict):
                return None

            v = (vendor_id or "").upper()

            timestamp = payload.get("timestamp", timezone.now())
            if isinstance(timestamp, str):
                try:
                    timestamp = timezone.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except Exception:
                    timestamp = timezone.now()

            if "soc" in payload:
                return {"percentage": payload.get("soc"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}
            if "batteryLevel" in payload:
                return {"percentage": payload.get("batteryLevel"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}
            if v == "SIEMENS" and isinstance(payload.get("stateOfCharge"), dict):
                return {"percentage": payload["stateOfCharge"].get("value"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}
            if v == "EVBOX" and isinstance(payload.get("vehicle"), dict) and "soc" in payload["vehicle"]:
                return {"percentage": payload["vehicle"].get("soc"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}
            if isinstance(payload.get("vehicle"), dict) and "soc" in payload["vehicle"]:
                return {"percentage": payload["vehicle"].get("soc"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}
            if "percentage" in payload:
                return {"percentage": payload.get("percentage"), "timestamp": timestamp, "source": f"vendor:{v.lower()}"}

            return None
        except Exception:
            return None

    async def process_vendor_soc(self, soc_data: dict):
        try:
            active_tx = await database_sync_to_async(
                lambda: (
                    Transaction.objects
                    .filter(connector__station_id=self.station_id, status="active")
                    .order_by("-started_at", "-id")
                    .first()
                )
            )()
            if active_tx:
                await self.save_soc_data(active_tx.transaction_id or active_tx.id, soc_data)
        except Exception:
            ocpp_logger.exception("Error processing vendor SoC")

    async def save_soc_data(self, transaction_id: int, soc_data: dict):
        try:
            pct = soc_data.get("percentage")
            ts = soc_data.get("timestamp", timezone.now())
            src = soc_data.get("source", "vendor")

            @database_sync_to_async
            def update_mv():
                tx = Transaction.objects.filter(transaction_id=int(transaction_id)).first()
                if not tx:
                    tx = Transaction.objects.filter(id=int(transaction_id)).first()
                if not tx:
                    return False
                
                MeterValue.objects.create(
                    transaction=tx, 
                    value=tx.meter_start,
                    soc_percentage=float(pct) if pct is not None else None,
                    timestamp=ts,
                    data={
                        "soc_percentage": pct,
                        "soc_timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                        "soc_source": src,
                        "samples": []
                    }
                )
                self._update_vehicle_soc(tx.vehicle, float(pct) if pct is not None else None, observed_at=ts)
                return True

            ok = await update_mv()
            if ok and getattr(self, "consumer", None) and pct is not None:
                await self.consumer.broadcast_soc_update(self.station_id, float(pct))
        except Exception:
            ocpp_logger.exception("Error saving SoC data")

    # -------------------------
    # Outbound calls (CS -> CP)
    # -------------------------
    async def call_authorize(self, id_tag: str):
        req = call.AuthorizePayload(id_tag=(id_tag or "")[:20])
        return await self._call_with_logging("Authorize", req)

    async def call_remote_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        requested_power_kw: Optional[float] = None,
        requested_power: Optional[float] = None,
        session_context: Optional[Dict[str, Any]] = None,
    ):
        """
        OCPP 1.6: RemoteStartTransaction supports chargingProfile (optional).
        requested_power_kw is used ONLY to build a chargingProfile (W limit).
        """
        id_tag = (id_tag or "")[:20]
        if requested_power_kw is None and requested_power is not None:
            requested_power_kw = requested_power
        self.pending_requested_power[(int(connector_id), id_tag)] = requested_power_kw
        self.pending_session_context[(int(connector_id), id_tag)] = session_context or {}

        charging_profile = None
        if requested_power_kw is not None:
            charging_profile = {
                "chargingProfileId": 1,
                "stackLevel": 1,
                "chargingProfilePurpose": "TxProfile",
                "chargingProfileKind": "Absolute",
                "chargingSchedule": {
                    "chargingRateUnit": "W",
                    "chargingSchedulePeriod": [{"startPeriod": 0, "limit": round(float(requested_power_kw) * 1000.0, 1)}],
                },
            }
            ocpp_logger.info(f"Created charging profile for {requested_power_kw}kW: {charging_profile}")
        else:
            ocpp_logger.info(f"No charging profile (Auto power - station will negotiate)")

        req = call.RemoteStartTransactionPayload(
            connector_id=int(connector_id),
            id_tag=id_tag,
            charging_profile=charging_profile,
        )

        return await self._call_with_logging("RemoteStartTransaction", req)

    async def call_remote_stop_transaction(self, transaction_id: int):
        req = call.RemoteStopTransactionPayload(transaction_id=int(transaction_id))
        return await self._call_with_logging("RemoteStopTransaction", req)

    async def call_change_availability(self, connector_id: int, availability_type: Union[str, AvailabilityType]):
        t = availability_type
        if isinstance(t, str):
            t = AvailabilityType(t)
        req = call.ChangeAvailabilityPayload(connector_id=int(connector_id), type=t)
        return await self._call_with_logging("ChangeAvailability", req)

    async def call_reset(self, reset_type: Union[str, ResetType] = "Soft"):
        t = reset_type
        if isinstance(t, str):
            t = ResetType(t)
        req = call.ResetPayload(type=t)
        return await self._call_with_logging("Reset", req)

    async def call_unlock_connector(self, connector_id: int):
        req = call.UnlockConnectorPayload(connector_id=int(connector_id))
        return await self._call_with_logging("UnlockConnector", req)

    async def call_clear_cache(self):
        req = call.ClearCachePayload()
        return await self._call_with_logging("ClearCache", req)

    async def call_get_configuration(self, keys=None):
        req = call.GetConfigurationPayload(key=keys)
        return await self._call_with_logging("GetConfiguration", req)

    async def call_change_configuration(self, key: str, value: str):
        req = call.ChangeConfigurationPayload(key=str(key), value=str(value))
        return await self._call_with_logging("ChangeConfiguration", req)

    async def call_trigger_message(self, requested_message: str, connector_id: Optional[int] = None):
        payload_kwargs = {"requested_message": str(requested_message)}
        if connector_id is not None:
            payload_kwargs["connector_id"] = int(connector_id)
        req = call.TriggerMessagePayload(**payload_kwargs)
        return await self._call_with_logging("TriggerMessage", req)


# -------------------------
# Channels WebSocket Consumer (OCPP endpoint for stations)
# -------------------------
class ChargePointConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_lock = asyncio.Lock()  # Lock за всички записи към SQLite
        self._is_closing = False  # Guard to prevent sends while closing
        self._connected = False   # Track websocket connection state

    async def connect(self):
        self.station_id = _normalize_station_key(self.scope["url_route"]["kwargs"]["station_id"])
        self.ocpp_identity = self.scope.get("url_route", {}).get("kwargs", {}).get("ocpp_identity")
        self._connected = True
        self._is_closing = False

        station_logger = get_station_logger(self.station_id)

        # Лог за опит за свързване
        try:
            get_station_logger(self.station_id).info("WS attempt: station=%s", self.station_id)
        except Exception:
            pass
        
        ocpp_logger.info(f"connect() called for station {self.station_id}, identity: {self.ocpp_identity}")

        # Избор на протокол
        offered = [p.lower() for p in self.scope.get("subprotocols", [])]
        chosen_subprotocol = "ocpp1.6" if "ocpp1.6" in offered else None
        
        ocpp_logger.info(f"Chosen subprotocol: {chosen_subprotocol}")

        # Приемане на връзката
        try:
            if chosen_subprotocol:
                await self.accept(subprotocol=chosen_subprotocol)
            else:
                await self.accept()
            
            get_station_logger(self.station_id).info("WS accepted: chosen_subprotocol=%s", chosen_subprotocol)
        except Exception as e:
            # ТУК ВНИМАВАЙ ЗА ИНДЕНТАЦИЯТА - трябва да е точно под 'try'
            get_station_logger(self.station_id).error("Accept failed: %s", str(e))
            return

        # Обновяване на базата
        if self.ocpp_identity:
            try:
                await database_sync_to_async(
                    lambda: Station.objects.filter(id=self.station_id).update(ocpp_identity=str(self.ocpp_identity))
                )()
            except Exception:
                pass

        # Стартиране на OCPP
        try:
            self.ws_wrapper = WebSocketWrapper(self)
            self.cp = ChargePoint(self.station_id, self.ws_wrapper, self)
            self.cp_task = asyncio.create_task(self.cp.start())
            
            ocpp_logger.info(f"ChargePoint created and task started for station {self.station_id}")
            
            def _log_cp_done(task: asyncio.Task) -> None:
                try:
                    exc = task.exception()
                except asyncio.CancelledError:
                    return
                except Exception:
                    exc = None
                if exc:
                    ocpp_logger.error(
                        "OCPP task crashed: station=%s error=%r",
                        getattr(self, "station_id", None),
                        exc,
                        exc_info=exc,
                    )

            try:
                self.cp_task.add_done_callback(_log_cp_done)
            except Exception:
                pass

            self.watchdog_task = asyncio.create_task(self.liveness_watchdog())
            ocpp_logger.info(f"Watchdog task started for station {self.station_id}")

            self.group_name = UI_HTML_GROUP
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            
            ocpp_logger.info(f"Station {self.station_id} added to UI_HTML_GROUP")
            
            # Also add to station-specific group for commands
            self.station_group_name = f"charging_stations_group_{self.station_id}"
            ocpp_logger.info(f"Attempting to add station {self.station_id} to group: {self.station_group_name}")
            await self.channel_layer.group_add(self.station_group_name, self.channel_name)
            
            ocpp_logger.info(f"Station {self.station_id} added to group: {self.station_group_name}")

            register_station(self.station_id, self)
            
            ocpp_logger.info(f"Station {self.station_id} registered in ACTIVE_STATIONS")

        except Exception as e:
            ocpp_logger.exception(f"Error during station initialization: {e}")
            await self.close(code=1011)


    async def disconnect(self, close_code):
        try:
            get_station_logger(getattr(self, "station_id", "?")).warning(
                "WS disconnect: station=%s close_code=%s close_reason=%s connected=%s closing=%s",
                getattr(self, "station_id", None),
                close_code,
                _ws_close_reason(close_code),
                getattr(self, "_connected", None),
                getattr(self, "_is_closing", None),
            )
        except Exception:
            pass
        await self.broadcast_station_offline()

        try:
            await self.update_station_status(self.station_id, "inactive", "disconnect")
        except Exception:
            ocpp_logger.exception("Error updating station status on disconnect")
        
        try:
            await database_sync_to_async(
                lambda: Connector.objects.filter(station_id=self.station_id).update(status="offline")
            )()
        except Exception:
            ocpp_logger.exception("Error updating connector status on disconnect")
        
        try:
            await self.broadcast_all_connectors_offline()
        except Exception:
            ocpp_logger.exception("Error broadcasting connectors offline")

        self._is_closing = True
        self._connected = False

        if hasattr(self, "cp_task"):
            self.cp_task.cancel()
            try:
                await self.cp_task
            except asyncio.CancelledError:
                pass

        if hasattr(self, "watchdog_task"):
            self.watchdog_task.cancel()
            try:
                await self.watchdog_task
            except asyncio.CancelledError:
                pass

        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            pass
        
        try:
            await self.channel_layer.group_discard(self.station_group_name, self.channel_name)
        except Exception:
            pass

        await database_sync_to_async(unregister_station)(self.station_id)

    async def remote_start_transaction(self, event):
        """Handle remote start transaction command from channel layer."""
        try:
            connector_id = event.get("connector_id")
            id_tag = event.get("id_tag")
            requested_power = event.get("requested_power")
            session_context = dict(event.get("session_context") or {})
            command_id = event.get("command_id")

            runtime_model = getattr(self.cp, "charge_point_model", None)
            runtime_vendor = getattr(self.cp, "charge_point_vendor", None)
            runtime_signature = " ".join(part for part in [runtime_model, runtime_vendor] if part).lower()
            if runtime_model:
                session_context.setdefault("runtime_charge_point_model", runtime_model)
            if runtime_vendor:
                session_context.setdefault("runtime_charge_point_vendor", runtime_vendor)
            if any(signature in runtime_signature for signature in {"simulator", "simulation", "avt-express"}):
                session_context.setdefault("runtime_type", "simulated")
                session_context.setdefault("session_source", "simulated")
            
            ocpp_logger.info(f"RemoteStartTransaction command received: station={self.station_id}, connector={connector_id}, id_tag={id_tag}, power={requested_power}")
            
            # Send command without waiting for response to avoid timeout issues
            # The station will process it and update status via StatusNotification
            try:
                # Create the task but don't await it
                task = asyncio.create_task(self.cp.call_remote_start_transaction(
                    connector_id=connector_id,
                    id_tag=id_tag,
                    requested_power=requested_power,
                    session_context=session_context,
                ))
                
                # Add callback to log response (Accepted/Rejected)
                def on_start_done(t):
                    try:
                        res = t.result()
                        ocpp_logger.info(f"RemoteStartTransaction response for station={self.station_id}: {res}")
                        if command_id:
                            asyncio.create_task(
                                self._record_command_result(
                                    command_id=command_id,
                                    response=res,
                                    success_detail="RemoteStartTransaction acknowledged by station",
                                    rejected_detail="RemoteStartTransaction rejected by station",
                                )
                            )
                    except Exception as e:
                        ocpp_logger.warning(f"RemoteStartTransaction task error: {e}")
                        if command_id:
                            asyncio.create_task(self._record_command_failure(command_id, e))
                task.add_done_callback(on_start_done)

                ocpp_logger.info(f"RemoteStartTransaction task created (fire-and-forget)")
            except Exception as e:
                ocpp_logger.warning(f"RemoteStartTransaction create task failed: {e}")
                if command_id:
                    await self._record_command_failure(command_id, e)
            
        except Exception as e:
            ocpp_logger.exception(f"RemoteStartTransaction handling failed: {e}")
            command_id = event.get("command_id")
            if command_id:
                await self._record_command_failure(command_id, e)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data or not hasattr(self, "ws_wrapper"):
            return
        
        # Track WebSocket performance
        try:
            st_id = getattr(self, "station_id", None)
            if st_id is not None:
                _msg_len = len(text_data)
                track_ws_performance(st_id, _msg_len, 'received')
                
                if _msg_len > 20000:
                    get_station_logger(st_id).warning("Large WS frame: station=%s bytes=%s", st_id, _msg_len)
        except Exception:
            pass
        
        # Pass to ws_wrapper for OCPP message handling
        if hasattr(self, "ws_wrapper"):
            await self.ws_wrapper.feed(text_data)


    async def remote_stop_transaction(self, event):
        """Handle remote stop transaction command from channel layer."""
        try:
            transaction_id = event.get("transaction_id")
            command_id = event.get("command_id")
            
            ocpp_logger.info(f"RemoteStopTransaction command received: station={self.station_id}, transaction_id={transaction_id}")
            
            # Send command without waiting for response to avoid timeout issues
            try:
                # Create the task but don't await it
                task = asyncio.create_task(self.cp.call_remote_stop_transaction(
                    transaction_id=transaction_id
                ))
                
                # Add callback to log response
                def on_stop_done(t):
                    try:
                        res = t.result()
                        ocpp_logger.info(f"RemoteStopTransaction response for station={self.station_id}: {res}")
                        if command_id:
                            asyncio.create_task(
                                self._record_command_result(
                                    command_id=command_id,
                                    response=res,
                                    success_detail="RemoteStopTransaction acknowledged by station",
                                    rejected_detail="RemoteStopTransaction rejected by station",
                                )
                            )
                    except Exception as e:
                        ocpp_logger.warning(f"RemoteStopTransaction task error: {e}")
                        if command_id:
                            asyncio.create_task(self._record_command_failure(command_id, e))
                task.add_done_callback(on_stop_done)
                
                ocpp_logger.info(f"RemoteStopTransaction task created (fire-and-forget)")
            except Exception as e:
                ocpp_logger.warning(f"RemoteStopTransaction create task failed: {e}")
                if command_id:
                    await self._record_command_failure(command_id, e)
            
        except Exception as e:
            ocpp_logger.exception(f"RemoteStopTransaction failed: {e}")
            command_id = event.get("command_id")
            if command_id:
                await self._record_command_failure(command_id, e)

    async def remote_stop_transaction_event(self, event):
        """Handle remote stop transaction command from channel layer (Channels naming convention)."""
        ocpp_logger.info(f"remote_stop_transaction_event called: station={self.station_id}, event={event}")
        await self.remote_stop_transaction(event)

    async def _record_command_result(self, command_id: str, response, success_detail: str, rejected_detail: str):
        await self._update_command_log(
            command_id=command_id,
            response_status=self._extract_response_status(response),
            detail=str(response),
            success_detail=success_detail,
            rejected_detail=rejected_detail,
        )

    async def _record_command_failure(self, command_id: str, exc: Exception):
        status = "timeout" if "timeout" in str(exc).lower() else "failed_at_station"
        await self._update_command_log(
            command_id=command_id,
            response_status=status,
            detail=str(exc),
            success_detail="",
            rejected_detail="",
        )

    def _extract_response_status(self, response) -> str:
        status = getattr(response, "status", None)
        if hasattr(status, "value"):
            status = status.value
        normalized = str(status or "").strip().lower()
        if normalized == "accepted":
            return "acknowledged"
        if normalized == "rejected":
            return "rejected"
        return "failed_at_station"

    @database_sync_to_async
    def _update_command_log(self, command_id: str, response_status: str, detail: str, success_detail: str, rejected_detail: str):
        command_log = CommandLog.objects.filter(command_id=command_id).first()
        if not command_log:
            return
        if command_log.status not in {"sent", "pending"}:
            return
        command_log.status = response_status
        if response_status == "acknowledged":
            command_log.detail = success_detail or detail
            command_log.error_message = ""
        elif response_status == "rejected":
            command_log.detail = rejected_detail or detail
            command_log.error_message = detail
        else:
            command_log.detail = detail or "Station command execution failed"
            command_log.error_message = detail
        command_log.executed_at = timezone.now()
        command_log.save(update_fields=["status", "detail", "error_message", "executed_at"])

    async def station_message(self, event):
        # UI_HTML_GROUP messages for templates; ignore here
        return

    # -------------------------
    # UI broadcast helpers (single schema)
    # -------------------------
    async def _ui_send(self, data: Dict[str, Any]) -> None:
        logger.info(f"Sending UI message: {data}")
        await self.channel_layer.group_send(
            UI_STATUS_GROUP,
            {"type": "broadcast", "data": data},
        )

    async def broadcast_station_status(self, station_id: int, status: str, reason: str = ""):
        await self._ui_send({
            "type": "station_status",
            "station_id": int(station_id),
            "status": status,
            "reason": reason,
            "timestamp": timezone.now().isoformat(),
        })

    async def broadcast_authorization_success(self, station_id: int, id_tag: str):
        await self._ui_send({
            "type": "authorization_success",
            "station_id": int(station_id),
            "id_tag": str(id_tag),
            "timestamp": timezone.now().isoformat(),
        })

    async def broadcast_connector_status(self, station_id: int, connector_status: str, connector_id: Optional[int] = None):
        station_id = int(station_id)
        connector_id = int(connector_id or 1)

        try:
            # Use update_or_create to avoid unique_together integrity errors under load
            conn, created = await database_sync_to_async(
                lambda: Connector.objects.update_or_create(
                    station_id=station_id,
                    connector_id=connector_id,
                    defaults={"status": connector_status},
                )
            )()

            await self._ui_send({
                "type": "connector_status_update",
                "station_id": station_id,
                "connector_id": connector_id,
                "connector_status": connector_status,
                "station_status": "inactive" if connector_status == "offline" else "active",
                "timestamp": timezone.now().isoformat(),
            })
        except Exception:
            ocpp_logger.exception("broadcast_connector_status failed")

    async def broadcast_all_connectors_offline(self):
        try:
            connector_ids = await database_sync_to_async(
                lambda: list(
                    Connector.objects.filter(station_id=self.station_id)
                    .values_list("connector_id", flat=True)
                    .order_by("connector_id")
                )
            )()
            if not connector_ids:
                connector_ids = [1]
            for cid in connector_ids:
                await self._ui_send({
                    "type": "connector_status_update",
                    "station_id": int(self.station_id),
                    "connector_id": int(cid),
                    "connector_status": "offline",
                    "station_status": "inactive",
                    "timestamp": timezone.now().isoformat(),
                })
        except Exception:
            return

    async def broadcast_station_offline(self):
        try:
            await self._ui_send({
                "type": "station_status",
                "station_id": int(self.station_id),
                "status": "offline",
                "action": "disconnect",
                "timestamp": timezone.now().isoformat(),
            })
        except Exception:
            return

    async def broadcast_soc_update(self, station_id: int, soc_percentage: float):
        try:
            # This is what stations_tab.js expects: data.type === "soc_update"
            await self._ui_send({
                "type": "soc_update",
                "station_id": int(station_id),
                "soc_percentage": float(soc_percentage),
                "timestamp": timezone.now().isoformat(),
            })
        except Exception:
            ocpp_logger.exception("broadcast_soc_update failed")

    # -------------------------
    # Station DB status update (used by disconnect/watchdog)
    # -------------------------
    @database_sync_to_async
    def _get_station(self, station_id: int):
        return Station.objects.get(id=station_id)

    @database_sync_to_async
    def _save_station(self, station: Station):
        station.save(update_fields=["status", "last_seen"])
        return station

    async def update_station_status(self, station_id: int, status: str, reason: str = "") -> bool:
        try:
            st = await self._get_station(int(station_id))
            async with self.db_lock:
                st.status = status
                if status == "active":
                    st.last_seen = timezone.now()
                await self._save_station(st)

            await self.broadcast_station_status(int(station_id), status=status, reason=reason)
            return True
        except Exception:
            ocpp_logger.exception("update_station_status failed")
            return False

    async def liveness_watchdog(self):
        try:
            while True:
                if not getattr(self, "_connected", False):
                    break
                await asyncio.sleep(5)
                if not hasattr(self, "cp"):
                    continue
                now = timezone.now()
                timeout_seconds = 300
                if (now - self.cp.last_seen) > timedelta(seconds=timeout_seconds):
                    try:
                        get_station_logger(getattr(self, "station_id", "?")).warning(
                            "Watchdog timeout: station=%s last_seen=%s now=%s diff_s=%s -> closing websocket",
                            getattr(self, "station_id", None),
                            getattr(self.cp, "last_seen", None),
                            now,
                            (now - self.cp.last_seen).total_seconds() if getattr(self, "cp", None) else None,
                        )
                    except Exception:
                        pass
                    await self.broadcast_station_offline()
                    await self.update_station_status(self.station_id, "inactive", "timeout")

                    await database_sync_to_async(
                        lambda: Connector.objects.filter(station_id=self.station_id).update(status="offline")
                    )()
                    await self.broadcast_all_connectors_offline()

                    self._is_closing = True
                    try:
                        await self.close()
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            return


# -------------------------
# Station Status Consumer (browser clients)
# -------------------------
class StationStatusConsumer(AsyncWebsocketConsumer):
    """
    Browser-facing WebSocket consumer.
    Listens to UI_STATUS_GROUP and forwards JSON as-is.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_closing = False
        self._connected = False

    async def connect(self):
        try:
            self._is_closing = False
            await self.channel_layer.group_add(UI_STATUS_GROUP, self.channel_name)
            await self.accept()
            self._connected = True
            await self.send_initial_snapshot()
        except Exception:
            self._connected = False
            self._is_closing = True
            try:
                await self.close()
            except Exception:
                pass

    async def disconnect(self, close_code):
        self._is_closing = True
        self._connected = False
        try:
            await self.channel_layer.group_discard(UI_STATUS_GROUP, self.channel_name)
        except Exception:
            pass

    async def receive(self, text_data=None, bytes_data=None):
        # UI doesn't need inbound messages; ignore safely
        return

    async def broadcast(self, event):
        if self._is_closing or not self._connected:
            return
        data = event.get("data")
        if not isinstance(data, dict):
            return
        try:
            await self.send(text_data=json.dumps(data))
        except Exception:
            return

    @database_sync_to_async
    def _snapshot(self) -> Dict[str, Any]:
        stations = list(Station.objects.all().prefetch_related("connectors"))
        active_keys = set(ACTIVE_STATIONS.keys())

        out = []
        for st in stations:
            # Use database status to determine online status
            # If station status is 'active', consider it online
            online = (st.status == 'active')
            if not online and st.id in active_keys:
                # Fallback to ACTIVE_STATIONS if database says inactive but station is connected
                online = True
            
            # Use status from database
            status = st.status if st.status else ("active" if online else "inactive")
            out.append({
                "station_id": st.id,
                "online": online,
                "status": status,
            })

        return {
            "type": "status_snapshot",
            "timestamp": timezone.now().isoformat(),
            "stations": out,
        }

    async def send_initial_snapshot(self):
        if self._is_closing or not self._connected:
            return
        try:
            snap = await self._snapshot()
            await self.send(text_data=json.dumps(snap))
        except Exception:
            return