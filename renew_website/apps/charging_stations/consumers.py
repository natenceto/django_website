# consumers.py
import asyncio
import json
import logging
import datetime as py_datetime
from datetime import timedelta
from typing import Dict, Any, Union, Optional, Tuple

from django.utils import timezone
from django.db import transaction as db_transaction
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

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
from .models import Station, Connector, Transaction, UserRFID, MeterValue
from .registry import ACTIVE_STATIONS


# -------------------------
# Logging
# -------------------------
ocpp_logger = get_ocpp_logger("consumers")
logger = logging.getLogger("charging_stations")


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
            _save_ws_metric_to_db(self.station_id, stats)
            stats['db_save_count'] += 1
        except Exception as e:
            get_station_logger(self.station_id).warning(f"Failed to save WebSocket metric to DB: {e}")


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
    ACTIVE_STATIONS[key] = consumer
    ocpp_logger.info(f"Station {key} registered in ACTIVE_STATIONS")


def unregister_station(station_id: Union[int, str]) -> None:
    key = _normalize_station_key(station_id)
    ACTIVE_STATIONS.pop(key, None)
    for d in (_last_heartbeat_log, _last_heartbeat_db_update, _rapid_heartbeat_count):
        d.pop(key, None)
    
    # Finalize WebSocket performance metric when station disconnects
    _finalize_ws_metric(station_id)
    
    ocpp_logger.info(f"Station {key} unregistered from ACTIVE_STATIONS")


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

        self.last_seen = timezone.now()
        self.heartbeat_interval = 60


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

        config = None
        try:
            config = await asyncio.wait_for(
                self.call_get_configuration(keys=["NumberOfConnectors"]),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            ocpp_logger.warning("GetConfiguration timeout (non-critical)")
        except Exception:
            ocpp_logger.exception("GetConfiguration failed (non-critical)")

        num_connectors = 1
        try:
            cfg_list = getattr(config, "configuration_key", None) if config else None
            if isinstance(cfg_list, (list, tuple)):
                for item in cfg_list:
                    if getattr(item, "key", None) == "NumberOfConnectors":
                        num_connectors = max(1, int(getattr(item, "value", 1)))
                        break
        except Exception:
            ocpp_logger.exception("Failed to parse NumberOfConnectors; using default 1")

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
        station_id = self.station_id
        station_logger = get_station_logger(self.station_id)

        get_station_logger(self.station_id).info("=== OCPP 1.6 BootNotification ===")
        get_station_logger(self.station_id).info(f"Station ID: {station_id}")
        get_station_logger(self.station_id).info(f"Vendor: {charge_point_vendor}")
        get_station_logger(self.station_id).info(f"Model: {charge_point_model}")

        firmware_version = kwargs.get("firmware_version") or kwargs.get("firmwareVersion")
        if firmware_version:
            get_station_logger(self.station_id).info(f"Firmware: {firmware_version}")

        self.heartbeat_interval = int(getattr(self, "default_heartbeat_interval", 60))
        get_station_logger(self.station_id).info(f"Heartbeat interval: {self.heartbeat_interval}s")

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

        return call_result.BootNotificationPayload(
            status=RegistrationStatus.accepted,
            current_time=current_time,
            interval=self.heartbeat_interval,
        )

    @on(Action.Authorize)
    async def on_authorize(self, id_tag: str, **kwargs):
        id_tag = (id_tag or "")[:20]

        try:
            is_valid = await database_sync_to_async(
                lambda: UserRFID.objects.filter(
                    tag=id_tag,
                    stations__id=self.station_id,
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

        return call_result.AuthorizePayload(id_tag_info={"status": status})

    @on(Action.StatusNotification)
    async def on_status_notification(self, connector_id: int, error_code: str, status: str, **kwargs):
        self.last_seen = timezone.now()
        station_id = self.station_id
        station_logger = get_station_logger(self.station_id)

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

        get_station_logger(self.station_id).info(
            f"StatusNotification: station={station_id} connectorId={connector_id} status={status} -> {normalized} errorCode={error_code}"
        )

        # connectorId=0 is station-level state
        if int(connector_id) == 0:
            s = (status or "").strip().lower()
            try:
                if s == "available":
                    asyncio.create_task(self._update_station_status_async("active", "status0"))
                elif s in {"faulted", "unavailable"}:
                    asyncio.create_task(self._update_station_status_async("inactive", "status0"))
            except Exception:
                ocpp_logger.exception("Failed scheduling station status update for connectorId=0")
            return call_result.StatusNotificationPayload()

        try:
            async with self.db_lock:

                @database_sync_to_async
                def upsert_connector():
                    conn, created = Connector.objects.get_or_create(
                        station_id=station_id,
                        connector_id=int(connector_id),
                        defaults={"status": normalized},
                    )
                    changed = False
                    old = conn.status
                    if old != normalized:
                        conn.status = normalized
                        conn.save(update_fields=["status"])
                        changed = True
                    return conn.id, created, changed, old

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

        return call_result.StatusNotificationPayload()

    @on(Action.Heartbeat)
    async def on_heartbeat(self):
        self.last_seen = timezone.now()
        station_id = self.station_id
        station_logger = get_station_logger(self.station_id)

        LOG_THROTTLE = 60
        DB_UPDATE_THROTTLE = 15
        RAPID_COUNT_LIMIT = 10

        now_ts = timezone.now()

        last_log = _last_heartbeat_log.get(station_id)
        if not last_log or (now_ts - last_log).total_seconds() >= LOG_THROTTLE:
            get_station_logger(self.station_id).info("Heartbeat received")
            _last_heartbeat_log[station_id] = now_ts

        last_db = _last_heartbeat_db_update.get(station_id)
        if not last_db or (now_ts - last_db).total_seconds() >= DB_UPDATE_THROTTLE:
            _last_heartbeat_db_update[station_id] = now_ts
            try:
                await self._touch_station_last_seen()
            except Exception:
                ocpp_logger.exception("Failed updating station last_seen")

        window = _rapid_heartbeat_count.setdefault(station_id, {"count": 0, "window_start": now_ts})
        if (now_ts - window["window_start"]).total_seconds() < LOG_THROTTLE:
            window["count"] += 1
        else:
            window["count"] = 1
            window["window_start"] = now_ts

        if window["count"] > RAPID_COUNT_LIMIT:
            get_station_logger(self.station_id).warning(f"Rapid heartbeats detected ({window['count']} in {LOG_THROTTLE}s)")

        current_time = (
            now_ts.astimezone(py_datetime.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return call_result.HeartbeatPayload(current_time=current_time)


    @on(Action.MeterValues)
    async def on_meter_values(
        self,
        connector_id: int,
        meter_value,
        transaction_id: Optional[int] = None,
        **kwargs,
    ):
        self.last_seen = timezone.now()

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
            return call_result.MeterValuesPayload()

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
                        return None

                agg, _ = MeterValue.objects.get_or_create(
                    transaction=tx,
                    defaults={
                        "value": tx.meter_start,
                        "data": {
                            "start": {"meter_start": tx.meter_start},
                            "samples": [],
                        },
                    },
                )

                data = agg.data or {}
                samples = data.get("samples") or []

                # ---------------------------
                # Append new samples
                # ---------------------------
                for mv in meter_value or []:
                    ts = mv.get("timestamp")

                    for sv in (mv.get("sampled_value") or []):
                        if sv.get("value") is None:
                            continue

                        samples.append(
                            {
                                "timestamp": ts,
                                "value": sv.get("value"),
                                "context": sv.get("context"),
                                "format": sv.get("format"),
                                "measurand": sv.get("measurand"),
                                "phase": sv.get("phase"),
                                "location": sv.get("location"),
                                "unit": sv.get("unit"),
                            }
                        )

                # ---------------------------
                # Prevent unbounded growth (keep last 500 samples)
                # ---------------------------
                MAX_SAMPLES = 500
                if len(samples) > MAX_SAMPLES:
                    samples = samples[-MAX_SAMPLES:]

                data["samples"] = samples
                agg.data = data

                # ---------------------------
                # Persist SoC if valid
                # ---------------------------
                if soc_percentage is not None:
                    agg.soc_percentage = soc_percentage
                    agg.soc_timestamp = soc_timestamp or timezone.now()
                    agg.soc_source = soc_source

                agg.save()

                return {
                    "station_id": self.station_id,
                    "soc_percentage": soc_percentage,
                }

            result = await persist()

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

        return call_result.MeterValuesPayload()


    @on(Action.DataTransfer)
    async def on_data_transfer(self, vendor_id: str, message_id: Optional[str] = None, data: Optional[str] = None, **kwargs):
        """
        Supports:
          - Generic / SoCData: data is JSON string {"soc": <num>, "timestamp": "<iso>"}
          - Optional vendor parsing based on Station.supports_vendor_soc + Station.vendor_id
        """
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
            return call_result.DataTransferPayload(status="Accepted")

        # Vendor SoC based on station config
        try:
            station_info = await database_sync_to_async(
                lambda: Station.objects.filter(id=self.station_id).values("vendor_id", "supports_vendor_soc").first()
            )()
        except Exception:
            station_info = None

        if station_info and station_info.get("supports_vendor_soc") and station_info.get("vendor_id") == vendor_id and data:
            try:
                soc_data = self.parse_vendor_soc_data(data, vendor_id)
                if soc_data:
                    await self.process_vendor_soc(soc_data)
            except Exception:
                ocpp_logger.exception("Error processing vendor DataTransfer")

        return call_result.DataTransferPayload(status="Accepted")

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

        mv = (
            MeterValue.objects
            .filter(transaction=tx)
            .order_by("-timestamp", "-id")
            .first()
        )
        if not mv:
            mv = MeterValue.objects.create(
                transaction=tx,
                value=tx.meter_start,
                timestamp=ts,
                data={"samples": []},
            )

        mv.soc_percentage = float(soc_value)
        mv.soc_timestamp = ts
        mv.soc_source = source
        mv.save(update_fields=["soc_percentage", "soc_timestamp", "soc_source"])

    @on(Action.DiagnosticsStatusNotification)
    async def on_diagnostics_status_notification(self, status: str, **kwargs):
        ocpp_logger.info(f"DiagnosticsStatusNotification: station={self.station_id} status={status}")
        return call_result.DiagnosticsStatusNotificationPayload()

    @on(Action.SecurityEventNotification)
    async def on_security_event_notification(self, type: str, timestamp: str, **kwargs):
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
        return call_result.SecurityEventNotificationPayload()

    @on(Action.StartTransaction)
    async def on_start_transaction(self, connector_id: int, id_tag: str, timestamp: str, meter_start: int, **kwargs):
        id_tag = (id_tag or "")[:20]

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
            return call_result.StartTransactionPayload(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid.value},
            )

        requested_power = self.pending_requested_power.get((int(connector_id), id_tag))

        async with self.db_lock:

            @database_sync_to_async
            def create_tx():
                with db_transaction.atomic():
                    conn, _ = Connector.objects.get_or_create(
                        station_id=self.station_id,
                        connector_id=int(connector_id),
                        defaults={"status": "available"},
                    )

                    tx = Transaction.objects.create(
                        connector=conn,
                        id_tag=id_tag,
                        meter_start=meter_start,
                        requested_power_kw=requested_power,
                        status="active",
                    )

                    # OCPP transactionId == returned transaction_id; store into tx.transaction_id
                    if hasattr(tx, "transaction_id"):
                        tx.transaction_id = int(tx.id)
                        tx.save(update_fields=["transaction_id"])

                    MeterValue.objects.get_or_create(
                        transaction=tx,
                        defaults={
                            "value": meter_start,
                            "data": {
                                "start": {"ocpp_timestamp": str(timestamp), "meter_start": meter_start},
                                "samples": [],
                            },
                        },
                    )

                    conn.status = "charging"
                    conn.save(update_fields=["status"])

                    return int(tx.id)

            tx_pk = await create_tx()

        self.pending_requested_power.pop((int(connector_id), id_tag), None)

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
        return call_result.StartTransactionPayload(
            transaction_id=int(tx_pk),
            id_tag_info={"status": AuthorizationStatus.accepted.value},
        )

    @on(Action.StopTransaction)
    async def on_stop_transaction(
        self,
        transaction_id: int,
        timestamp: str,
        meter_stop: int,
        id_tag: Optional[str] = None,
        reason: Optional[str] = None,
        **kwargs,
    ):
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

                    tx.meter_stop = meter_stop
                    tx.stopped_at = timezone.now()
                    tx.status = "completed"
                    tx.save(update_fields=["meter_stop", "stopped_at", "status"])

                    conn = tx.connector
                    if conn:
                        conn.status = "available"
                        conn.save(update_fields=["status"])

                    try:
                        MeterValue.objects.create(
                            transaction=tx,
                            value=meter_stop,
                            data={
                                "type": "final",
                                "ocpp_timestamp": str(timestamp),
                                "meter_start": tx.meter_start,
                                "meter_stop": meter_stop,
                                "reason": safe_reason,
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

        return call_result.StopTransactionPayload(
            id_tag_info={"status": AuthorizationStatus.accepted.value}
        )

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

            if "soc" in payload:
                return {"percentage": payload.get("soc"), "timestamp": payload.get("timestamp", timezone.now()), "source": "vendor"}
            if "batteryLevel" in payload:
                return {"percentage": payload.get("batteryLevel"), "timestamp": payload.get("timestamp", timezone.now()), "source": "vendor"}
            if v == "SIEMENS" and isinstance(payload.get("stateOfCharge"), dict):
                return {"percentage": payload["stateOfCharge"].get("value"), "timestamp": timezone.now(), "source": "vendor"}
            if v == "EVBOX" and isinstance(payload.get("vehicle"), dict) and "soc" in payload["vehicle"]:
                return {"percentage": payload["vehicle"].get("soc"), "timestamp": timezone.now(), "source": "vendor"}
            if "percentage" in payload:
                return {"percentage": payload.get("percentage"), "timestamp": payload.get("timestamp", timezone.now()), "source": "vendor"}

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
                mv = (
                    MeterValue.objects
                    .filter(transaction=tx)
                    .order_by("-timestamp", "-id")
                    .first()
                )
                if not mv:
                    mv = MeterValue.objects.create(transaction=tx, value=tx.meter_start, data={"samples": []})
                mv.soc_percentage = pct
                mv.soc_timestamp = ts
                mv.soc_source = src
                mv.save(update_fields=["soc_percentage", "soc_timestamp", "soc_source"])
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
        return await self.call(req)

    async def call_remote_start_transaction(
        self,
        connector_id: int,
        id_tag: str,
        requested_power_kw: Optional[float] = None,
        requested_power: Optional[float] = None,
    ):
        """
        OCPP 1.6: RemoteStartTransaction supports chargingProfile (optional).
        requested_power_kw is used ONLY to build a chargingProfile (W limit).
        """
        id_tag = (id_tag or "")[:20]
        if requested_power_kw is None and requested_power is not None:
            requested_power_kw = requested_power
        self.pending_requested_power[(int(connector_id), id_tag)] = requested_power_kw

        charging_profile = None
        if requested_power_kw is not None:
            charging_profile = {
                "chargingProfileId": 1,
                "stackLevel": 1,
                "chargingProfilePurpose": "TxProfile",
                "chargingProfileKind": "Absolute",
                "chargingSchedule": {
                    "chargingRateUnit": "W",
                    "chargingSchedulePeriod": [{"startPeriod": 0, "limit": float(requested_power_kw) * 1000.0}],
                },
            }

        req = call.RemoteStartTransactionPayload(
            connector_id=int(connector_id),
            id_tag=id_tag,
            charging_profile=charging_profile,
        )
        return await self.call(req)

    async def call_remote_stop_transaction(self, transaction_id: int):
        req = call.RemoteStopTransactionPayload(transaction_id=int(transaction_id))
        return await self.call(req)

    async def call_change_availability(self, connector_id: int, availability_type: Union[str, AvailabilityType]):
        t = availability_type
        if isinstance(t, str):
            t = AvailabilityType(t)
        req = call.ChangeAvailabilityPayload(connector_id=int(connector_id), type=t)
        return await self.call(req)

    async def call_reset(self, reset_type: Union[str, ResetType] = "Soft"):
        t = reset_type
        if isinstance(t, str):
            t = ResetType(t)
        req = call.ResetPayload(type=t)
        return await self.call(req)

    async def call_unlock_connector(self, connector_id: int):
        req = call.UnlockConnectorPayload(connector_id=int(connector_id))
        return await self.call(req)

    async def call_get_configuration(self, keys=None):
        req = call.GetConfigurationPayload(key=keys)
        return await self.call(req)


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

        # Избор на протокол
        offered = self.scope.get("subprotocols") or []
        chosen_subprotocol = None
        if "ocpp1.6" in offered:
            chosen_subprotocol = "ocpp1.6"
        elif "OCPP1.6" in offered:
            chosen_subprotocol = "OCPP1.6"

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
            
        except Exception as e:
            logger.error("CP task failed: %s", str(e))
            await self.close()


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

            self.group_name = UI_HTML_GROUP
            await self.channel_layer.group_add(self.group_name, self.channel_name)

            register_station(self.station_id, self)

        except Exception:
            ocpp_logger.exception("Error during station initialization")
            await self.close(code=1011)


    async def disconnect(self, close_code):
        try:
            get_station_logger(getattr(self, "station_id", "?")).warning(
                "WS disconnect: station=%s close_code=%s connected=%s closing=%s",
                getattr(self, "station_id", None),
                close_code,
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

        unregister_station(self.station_id)

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
        
        try:
            json.loads(text_data)
        except Exception:
            if text_data.strip().lower() == "ping":
                await self.send(text_data="pong")
            return

        await self.ws_wrapper.feed(text_data)

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
            conn = await database_sync_to_async(
                lambda: Connector.objects.filter(station_id=station_id, connector_id=connector_id).first()
            )()

            if not conn:
                conn = await database_sync_to_async(Connector.objects.create)(
                    station_id=station_id,
                    connector_id=connector_id,
                    status=connector_status,
                )
            else:
                if conn.status != connector_status:
                    conn.status = connector_status
                    await database_sync_to_async(conn.save)(update_fields=["status"])

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