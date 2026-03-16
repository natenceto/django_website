"""
OCPP WebSocket Consumers for EV Charging Platform.

This module contains:
- ChargePoint: OCPP 1.6 protocol handler
- ChargePointConsumer: WebSocket consumer for charging stations
- StationStatusConsumer: WebSocket consumer for browser clients

Module structure (future refactoring):
- ocpp/registry.py: Active stations registry
- ocpp/websocket.py: WebSocket wrapper for OCPP
- ocpp/chargepoint.py: ChargePoint class (to be moved)
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import transaction as db_transaction
from ocpp.routing import on
from ocpp.v16 import ChargePoint as OCPPChargePoint
from ocpp.v16 import call, call_result
from ocpp.v16.enums import RegistrationStatus, Action, AuthorizationStatus, AvailabilityType, ResetType, RemoteStartStopStatus

# Import models at module level
from .models import Station, Connector, Transaction, UserRFID, MeterValue

# Global registry for active stations
ACTIVE_STATIONS = {}

# Global heartbeat tracking
_last_heartbeat_log = {}

def register_station(station_id, consumer):
    """Register a station as active."""
    ACTIVE_STATIONS[station_id] = consumer
    print(f"Station {station_id} registered in ACTIVE_STATIONS")
    print(f"[DEBUG] ACTIVE_STATIONS after register: {list(ACTIVE_STATIONS.keys())}")

def unregister_station(station_id):
    """Unregister a station."""
    if station_id in ACTIVE_STATIONS:
        del ACTIVE_STATIONS[station_id]
        print(f"Station {station_id} unregistered from ACTIVE_STATIONS")
        print(f"[DEBUG] ACTIVE_STATIONS after unregister: {list(ACTIVE_STATIONS.keys())}")
        
        # Clean up heartbeat tracking
        if station_id in _last_heartbeat_log:
            del _last_heartbeat_log[station_id]
            print(f"[DEBUG] Cleaned up heartbeat tracking for station {station_id}")
    else:
        print(f"[DEBUG] Station {station_id} not found in ACTIVE_STATIONS for unregister")

# Logger for this module
logger = logging.getLogger('charging_stations')

# -------------------------
# WebSocket wrapper for OCPP
# -------------------------
class WebSocketWrapper:
    def __init__(self, consumer):
        self.consumer = consumer
        self.queue = asyncio.Queue()

    async def send(self, message):
        # Guard against sending after close - silently ignore instead of raising
        if not getattr(self.consumer, "_connected", False) or getattr(self.consumer, "_is_closing", False):
            return  # Silently ignore sends after close
        try:
            await self.consumer.send(text_data=message)
        except RuntimeError:
            # Connection already closed, ignore
            pass

    async def recv(self):
        return await self.queue.get()

    async def feed(self, message):
        # Check if this is a WebSocket ping message
        if message.strip() == "ping" or message.strip() == "PING":
            # Silently handle ping/pong
            await self.send("pong")
            return
        
        await self.queue.put(message)

# -------------------------
# OCPP ChargePoint class
# -------------------------
class ChargePoint(OCPPChargePoint):
    def __init__(self, station_id, websocket, consumer):
        super().__init__(station_id, websocket)
        # Ensure station_id is consistently an int for DB lookups
        try:
            self.station_id = int(station_id)
        except Exception:
            self.station_id = station_id
        self.consumer = consumer
        self.pending_requested_power = {}  # Store requested power per (connector_id, id_tag)
        self.db_lock = asyncio.Lock()
        # Connection tracking
        self.last_seen = timezone.now()
        self._connection_verified = False
        self._heartbeat_task = None
        self._connection_retries = 0
        self._max_retries = 3
        self._watchdog_task = None
    
    async def route_message(self, raw_msg):
        """Override to handle malformed messages from simulator"""
        try:
            # Update liveness on any inbound message
            self.last_seen = datetime.now().astimezone()
            return await super().route_message(raw_msg)
        except Exception as e:
            # Suppress malformed error messages from simulator (incomplete CallError)
            error_str = str(e)
            if ("Payload for Action is incomplete" in error_str or 
                "missing 2 required positional arguments" in error_str or
                "doesn't seem to be valid OCPP" in error_str):
                print(f"Ignoring malformed message from simulator: {raw_msg}")
                return
            # Re-raise other exceptions
            raise

    # HEARTBEAT SENDER REMOVED - Central System should NOT send Heartbeat requests
    # Only Charge Points should send Heartbeat to Central System

    @database_sync_to_async
    def update_station_model(self, station_id, model, vendor=None):
        """Update station model and vendor information."""
        from .models import Station
        try:
            station = Station.objects.get(id=station_id)
            if not station.model:  # Only update if model is not already set
                station.model = model
                if vendor and not station.connector_type:  # Set connector type if not set
                    station.connector_type = vendor
                station.save()
                print(f"Updated station {station_id} model to {model}")
            return True
        except Exception as e:
            print(f"Error updating station model: {e}")
            return False

    async def _debug_connection(self):
        """Debug connection status and handshake"""
        try:
            print("\n=== Connection Debug ===")
            print(f"Station ID: {getattr(self, 'station_id', 'N/A')}")
            print(f"WebSocket state: {'OPEN' if hasattr(self, '_connection') and self._connection.open else 'CLOSED'}")
            print(f"Last seen: {getattr(self, 'last_seen', 'Never')}")
            print(f"Heartbeat interval: {getattr(self, 'heartbeat_interval', 'N/A')}s")
            
            # Try a simple ping
            try:
                await asyncio.wait_for(self.call_heartbeat(), timeout=2.0)
                print("Ping successful")
                return True
            except Exception as e:
                print(f"Ping failed: {e}")
                return False
                
        except Exception as e:
            print(f"Debug error: {e}")
            return False

    async def verify_connection(self):
        """Verify the connection is working properly."""
        try:
            print("\n=== Verifying Connection ===")
            print("Sending GetConfiguration request...")
            
            # Add timeout to prevent hanging
            config = await asyncio.wait_for(
                self.call_get_configuration(keys=["HeartbeatInterval"]), 
                timeout=5.0  # 5 seconds timeout
            )
            print(f"Got configuration: {config}")
            
            # Check if we can get meter values
            print("Requesting meter values...")
            try:
                meter = await asyncio.wait_for(
                    self.call_meter_values(connector_id=0), 
                    timeout=3.0  # 3 seconds timeout
                )
                print(f"Got meter values: {meter}")
            except Exception as e:
                print(f"Could not get meter values (may be normal): {e}")
                
            print("Connection verification complete")
            return True
            
        except asyncio.TimeoutError:
            print("Connection verification failed: timeout")
            return False
        except Exception as e:
            print(f"Connection verification failed: {e}")
            return False

    async def _connection_watchdog(self):
        """Monitor the connection and attempt recovery if needed."""
        while True:
            try:
                if not hasattr(self, 'last_seen') or (timezone.now() - self.last_seen).total_seconds() > self.heartbeat_interval * 2:
                    print("No recent activity, checking connection...")
                    if not await self._debug_connection():
                        print("Connection appears down, attempting to recover...")
                        self._connection_retries += 1
                        if self._connection_retries > self._max_retries:
                            print("Max retries reached, giving up...")
                            break
                            
                        # Try to reset the connection safely
                        try:
                            if hasattr(self, 'consumer') and hasattr(self.consumer, 'close'):
                                await self.consumer.close()
                            await asyncio.sleep(1)
                            # Reconnect logic would go here
                        except Exception as e:
                            print(f"Error during connection reset: {e}")
                            break
                else:
                    self._connection_retries = 0  # Reset retry counter on successful activity
                
                await asyncio.sleep(self.heartbeat_interval)
                
            except asyncio.CancelledError:
                print("Watchdog task cancelled")
                break
            except Exception as e:
                print(f"Watchdog error: {e}")
                await asyncio.sleep(5)  # Prevent tight loop on error

    @on(Action.BootNotification)
    async def on_boot_notification(self, charge_point_model=None, charge_point_vendor=None, **kwargs):
        """Optimized boot notification handler with minimal blocking operations."""
        try:
            self.last_seen = timezone.now()
            current_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
            station_id = getattr(self, "station_id", None)
            
            # Log boot notification
            print("\n=== OCPP 1.6 BootNotification ===")
            print(f"Station ID: {station_id}")
            if charge_point_model:
                print(f"Model: {charge_point_model}")
            if charge_point_vendor:
                print(f"Vendor: {charge_point_vendor}")
            if kwargs.get('firmware_version'):
                print(f"Firmware: {kwargs.get('firmware_version')}")
            
            # Set heartbeat interval (default 60s, can be overridden by station)
            self.heartbeat_interval = 60
            print(f"Heartbeat interval: {self.heartbeat_interval}s")
            print("Status: Accepted\n")
            
            # Start async tasks that can run in parallel
            model_update_task = None
            if charge_point_model and station_id:
                model_update_task = asyncio.create_task(
                    self.update_station_model(station_id, charge_point_model, charge_point_vendor)
                )
            
            # Update station status without waiting for completion
            status_task = asyncio.create_task(
                self._update_station_status_async('active', 'boot') if station_id else asyncio.sleep(0)
            )
            
            # Schedule post-boot setup to run in background
            asyncio.create_task(self._post_boot_setup())
            
            # Wait for critical tasks to complete (with timeout to prevent hanging)
            if model_update_task:
                try:
                    await asyncio.wait_for(model_update_task, timeout=2.0)
                except asyncio.TimeoutError:
                    print("Warning: Model update took too long, continuing...")
            
            try:
                await asyncio.wait_for(status_task, timeout=1.0)
            except asyncio.TimeoutError:
                print("Warning: Status update took too long, continuing...")
            
            # Start watchdog if not already running
            if not hasattr(self, '_watchdog_task') or self._watchdog_task is None or self._watchdog_task.done():
                self._watchdog_task = asyncio.create_task(self._connection_watchdog())
                print("Started connection watchdog")
            
            # Skip connection verification to avoid disconnect
            # asyncio.create_task(self._post_boot_verification())
            
            # Return response immediately
            return call_result.BootNotificationPayload(
                current_time=current_time,
                interval=self.heartbeat_interval,
                status=RegistrationStatus.accepted
            )
            
        except Exception as e:
            print(f"Error in boot notification (non-critical): {e}")
            # Always return a response to the station
            return call_result.BootNotificationPayload(
                current_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                interval=60,
                status=RegistrationStatus.accepted
            )
    
    async def _update_station_status_async(self, status, reason=""):
        """Update station status in the database and broadcast to clients"""
        try:
            # Database update in sync context
            @database_sync_to_async
            def update_db():
                with db_transaction.atomic():
                    station = Station.objects.select_for_update().filter(id=self.station_id).first()
                    if station and station.status != status:
                        old_status = station.status
                        station.status = status
                        station.last_seen = timezone.now()
                        station.save(update_fields=['status', 'last_seen'])
                        print(f"Station {self.station_id} status updated: {old_status} -> {status} (Reason: {reason})")
                        return True
                return False
            
            updated = await update_db()
            
            # Broadcast to WebSocket clients (in async context)
            if updated and hasattr(self, 'consumer') and self.consumer:
                try:
                    await self.consumer.broadcast_status_update(status, reason)
                except Exception as e:
                    print(f"Error broadcasting status update: {e}")
            
            return updated
        except Exception as e:
            print(f"Error in _update_station_status_async: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _post_boot_setup(self):
        """Optimized background setup with batched operations."""
        try:
            # Don't proceed if connection already closed
            if not getattr(self.consumer, "_connected", False):
                return
                
            # Get configuration with timeout
            try:
                config = await asyncio.wait_for(
                    self.call_get_configuration(keys=["NumberOfConnectors"]), 
                    timeout=3.0
                )
            except (asyncio.TimeoutError, Exception) as e:
                print(f"Warning: Could not get configuration: {e}")
                config = None
            
            # Determine number of connectors
            num_connectors = 1  # Default to 1 connector
            if config:
                # Try to extract number of connectors from response
                config_list = None
                if isinstance(config, dict):
                    config_list = config.get('configurationKey') or config.get('configuration_key') or config.get('key')
                else:
                    config_list = getattr(config, 'configuration_key', None) or getattr(config, 'configurationKey', None)
                
                if isinstance(config_list, (list, tuple)):
                    for item in config_list:
                        k = (item.get('key') if isinstance(item, dict) else getattr(item, 'key', None))
                        if (k or '').lower() == 'numberofconnectors':
                            v = item.get('value') if isinstance(item, dict) else getattr(item, 'value', None)
                            try:
                                num_connectors = max(1, int(v))
                                break
                            except (ValueError, TypeError):
                                pass
            
            # Batch create missing connectors
            await self._batch_create_connectors(num_connectors)
            
            # REMOVED: call_status_notification - doesn't exist in OCPP 1.6
            # Chargers send StatusNotification on their own via @on(Action.StatusNotification)
        except Exception as e:
            print(f"Error in post-boot setup: {e}")
            import traceback
            traceback.print_exc()
    
    @database_sync_to_async
    def _batch_create_connectors(self, num_connectors):
        """Efficiently create missing connectors in a single query."""
        from django.db.models import Q
        from .models import Connector
        
        if not hasattr(self, 'station_id') or not self.station_id:
            return
            
        # Get existing connector IDs in a single query
        existing = set(Connector.objects.filter(
            station_id=self.station_id
        ).values_list('connector_id', flat=True))
        
        # Prepare new connectors
        new_connectors = [
            Connector(
                station_id=self.station_id,
                connector_id=conn_id,
                status='available',
                created_at=timezone.now(),
                updated_at=timezone.now()
            )
            for conn_id in range(1, num_connectors + 1)
            if conn_id not in existing
        ]
        
        # Batch create all new connectors
        if new_connectors:
            Connector.objects.bulk_create(new_connectors)
            print(f"Created {len(new_connectors)} new connectors for station {self.station_id}")

    @on(Action.StatusNotification)
    async def on_status_notification(self, connector_id: int, error_code: str, status: str, **kwargs):
        """
        Handle StatusNotification message from the charging station.
        Updates the connector status in the database.
        """
        from .models import Connector, Transaction, MeterValue
        
        # Update last_seen on every StatusNotification to prevent watchdog timeout
        self.last_seen = timezone.now()
        
        # Clean status notification output
        print("\n=== OCPP 1.6 StatusNotification ===")
        print(f"Station ID: {getattr(self, 'station_id', 'N/A')}")
        print(f"Connector: {connector_id}")
        print(f"Status: {status}")
        if error_code and error_code != 'NoError':
            print(f"Error Code: {error_code}")
            
        # Log important status changes
        if status in ['Charging', 'SuspendedEVSE', 'SuspendedEV']:
            print(f"Charging session in progress (Status: {status})")
        elif status == 'Available':
            print("Connector is available")
            
        # Extract and log timestamp if available
        timestamp = kwargs.get('timestamp')
        if timestamp:
            print(f"Timestamp: {timestamp}")
            
        print()  # Add spacing between notifications
        
        # Extract vendor_connector_id from various possible locations
        vendor_connector_id = None
        info = kwargs.get('info', '')
        
        # Debug: Log all available fields in the message
        print(f"[DEBUG] All available fields in StatusNotification: {', '.join(kwargs.keys())}")
        
        # Check common locations for vendor connector ID
        vendor_connector_id = (
            # Direct fields
            kwargs.get('vendor_connector_id') or 
            kwargs.get('vendorConnectorId') or
            kwargs.get('connectorCode') or
            kwargs.get('connector_id') or
            # Sometimes it's in the vendor_error_code
            (kwargs.get('vendor_error_code') if kwargs.get('vendor_error_code') not in ['0x0000', '0', ''] else None) or
            # Check if serial number is in the path (from WebSocket URL)
            (getattr(self.consumer, 'serial_number', None) if hasattr(self, 'consumer') else None)
        )
        
        if vendor_connector_id:
            print(f"[DEBUG] Found vendor_connector_id in message fields: {vendor_connector_id}")
        
        # Only process info field if it's not None, empty, or 'null' string
        if info and str(info).strip().lower() not in ['', 'null']:
            print(f"[DEBUG] Raw info field content: {info}")  # Debug log
            
            # Try to parse info as JSON if it looks like JSON
            if info.strip().startswith('{') and info.strip().endswith('}'):
                try:
                    info_json = json.loads(info)
                    print(f"[DEBUG] Parsed info JSON: {info_json}")  # Debug log
                    
                    # Look for common vendor-specific connector ID fields
                    vendor_id_fields = [
                        'vendorConnectorId', 'vendor_connector_id', 'connectorCode', 
                        'externalId', 'connector_id', 'connectorId', 'id', 'connector',
                        'connectorID', 'connector_id_number', 'serial_number', 'sn',
                        'connector_serial', 'connectorSerial', 'connectorSerialNumber'
                    ]
                    
                    # Try exact matches first (case sensitive)
                    for field in vendor_id_fields:
                        if field in info_json:
                            vendor_connector_id = str(info_json[field])
                            print(f"[DEBUG] Found vendor_connector_id in field '{field}': {vendor_connector_id}")
                            break
                    
                    # If not found, try case-insensitive search
                    if not vendor_connector_id:
                        info_lower = {k.lower(): v for k, v in info_json.items()}
                        for field in [f.lower() for f in vendor_id_fields]:
                            if field in info_lower:
                                vendor_connector_id = str(info_lower[field])
                                print(f"[DEBUG] Found vendor_connector_id (case-insensitive) in field '{field}': {vendor_connector_id}")
                                break
                    
                    # If still not found, try to find any field that might contain an ID
                    if not vendor_connector_id:
                        for k, v in info_json.items():
                            if isinstance(v, str) and any(term in k.lower() for term in ['id', 'connector', 'serial']):
                                vendor_connector_id = str(v)
                                print(f"[DEBUG] Found potential ID in field '{k}': {vendor_connector_id}")
                                break
                                
                except json.JSONDecodeError:
                    print("[DEBUG] Info is not valid JSON, trying string patterns")  # Debug log
                    # If not JSON, try to extract ID from string patterns
                    import re
                    # Common patterns for extracting IDs from strings
                    patterns = [
                        r'[Cc]onnector[ _-]?[Ii][Dd][:=]\s*["\']?([\w-]+)["\']?',
                        r'[Ii][Dd][:=]\s*["\']?([\w-]+)["\']?',
                        r'[Ss]erial[ _-]?[Nn]o?[\s:=]+["\']?([\w-]+)["\']?',
                        r'[Cc]onnector[\s:]+([\w-]+)',
                        r'ID[\s:]+([\w-]+)',
                        r'([A-Z]{2,3}\d{4,})',  # Common ID patterns like AB1234, XYZ56789
                        r'(\d{4,})'  # Any 4+ digit number
                    ]
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, info)
                        if matches:
                            # Take the first non-empty match
                            for match in matches:
                                if match:  # Ensure match is not empty
                                    vendor_connector_id = match
                                    print(f"[DEBUG] Extracted ID using pattern '{pattern}': {vendor_connector_id}")
                                    break
                            if vendor_connector_id:
                                break
        
        # Normalize OCPP status to model choices
        def normalize_status(s: str) -> str:
            s_lower = (s or "").strip().lower()
            # Map OCPP 1.6 statuses to our model choices
            mapping = {
                "available": "available",
                "preparing": "preparing",
                "charging": "charging",
                "suspendedev": "suspendedEV",
                "suspendedevse": "suspendedEVSE",
                "finishing": "finishing",
                "reserved": "reserved",
                "faulted": "faulted",
                # OCPP has "unavailable" which we represent as "offline"
                "unavailable": "offline",
            }
            # direct match first
            if s_lower in mapping:
                return mapping[s_lower]
            # handle exact case strings already matching model
            allowed = {"available","preparing","charging","suspendedEV","suspendedEVSE","finishing","reserved","faulted","offline"}
            if status in allowed:
                return status
            return "available"

        normalized_status = normalize_status(status)

        # ConnectorId 0 is the EVSE (charge point) status, not a physical connector. Don't create DB records for it.
        if connector_id == 0:
            # Optionally, we could update station-level status here, but avoid creating a Connector(0)
            print("Ignoring connector_id 0 for DB creation; treated as station-level status")
            return call_result.StatusNotificationPayload()

        # Update connector status in database
        try:
            async with self.db_lock:
                def get_or_create_connector():
                    # Prepare defaults including vendor_connector_id if available
                    defaults = {
                        "status": normalized_status,
                    }
                    if vendor_connector_id:
                        defaults["vendor_connector_id"] = vendor_connector_id
                    
                    # Create or update connector record
                    connector, created = Connector.objects.get_or_create(
                        station_id=self.station_id,
                        connector_id=connector_id,
                        defaults=defaults
                    )
                    
                    # If connector exists, update vendor_connector_id if not already set or different
                    if not created and vendor_connector_id and connector.vendor_connector_id != vendor_connector_id:
                        connector.vendor_connector_id = vendor_connector_id
                        connector.save(update_fields=['vendor_connector_id'])
                    
                    return connector, created
                    
                connector, created = await database_sync_to_async(get_or_create_connector)()
                
                if created:
                    print(f"Connector {connector_id} created with status {normalized_status}")
                elif connector.status != normalized_status:
                    old_status = connector.status
                    connector.status = normalized_status
                    await database_sync_to_async(connector.save)()
                    print(f"Connector {connector_id} status updated: {old_status} -> {normalized_status}")
                
                # Reconcile orphan active transaction if connector moves to a terminal/non-charging state
                if normalized_status in ["available", "faulted"]:
                    def finalize_active_transaction():
                        # Find latest active transaction for this connector
                        tx = (
                            Transaction.objects
                            .filter(connector=connector, status="active")
                            .order_by("-id")
                            .first()
                        )
                        if not tx:
                            return None
                        # Try to get the latest meter value to use as meter_stop
                        last_mv = (
                            MeterValue.objects
                            .filter(transaction=tx)
                            .order_by("-timestamp")
                            .first()
                        )
                        if last_mv:
                            tx.meter_stop = last_mv.value
                        tx.stopped_at = datetime.now().astimezone()
                        tx.status = "completed" if status == "available" else "error"
                        tx.save()
                        return tx.id
                    finalized_tx_id = await database_sync_to_async(finalize_active_transaction)()
                    if finalized_tx_id:
                        print(f"Reconciled transaction {finalized_tx_id} due to connector status '{status}'")

                # Ensure station is marked active even if BootNotification wasn't received
                if hasattr(self, 'consumer'):
                    await self.consumer.update_station_status(self.station_id, "active", "status")
                    # Broadcast connector status AFTER station status so UI updates correctly
                    await self.consumer.broadcast_connector_status(self.station_id, normalized_status)
        except Exception as e:
            print(f"Error updating connector status: {e}")
        
        return call_result.StatusNotificationPayload()


    # DUPLICATE _post_boot_setup METHODS REMOVED - Using the first implementation above

    async def _post_boot_verification(self):
        """Run after boot to verify the connection is stable."""
        # Completely disable post-boot verification to avoid disconnect
        print("[DEBUG] Skipping post-boot verification to maintain connection")
        
        # If we have a consumer, update the status
        if hasattr(self, 'consumer') and hasattr(self, 'station_id'):
            await self.consumer.update_station_status(self.station_id, "active", "boot")

    @on(Action.Heartbeat)
    async def on_heartbeat(self):
        """Handle heartbeat from charging station."""
        self.last_seen = timezone.now()
        local_time = timezone.localtime(self.last_seen)
        
        # Only log every 60 seconds to reduce spam
        # Use simple global variable to persist between calls
        global _last_heartbeat_log
        
        station_id = getattr(self, 'station_id', '?')
        if station_id not in _last_heartbeat_log:
            _last_heartbeat_log[station_id] = None
        
        current_time = timezone.now()
        last_log = _last_heartbeat_log[station_id]
        
        # Debug: Check time difference
        time_diff = 0
        if last_log is not None:
            time_diff = (current_time - last_log).total_seconds()
        
        if (last_log is None or time_diff >= 60):
            print(f"[Heartbeat] Station {station_id} - {local_time.strftime('%H:%M:%S')} (diff: {time_diff:.0f}s)")
            _last_heartbeat_log[station_id] = current_time
        else:
            # Skip logging to reduce spam
            pass
        
        # Update last seen in database
        if hasattr(self, 'station_id') and self.station_id:
            await self._update_station_last_seen()
            
        return call_result.HeartbeatPayload(
            current_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        )
        
    @database_sync_to_async
    def _update_station_last_seen(self):
        """Update station's last seen timestamp."""
        from .models import Station
        try:
            Station.objects.filter(id=self.station_id).update(
                last_seen=timezone.now()
            )
        except Exception as e:
            print(f"Error updating last_seen: {e}")

    # DUPLICATE _post_boot_setup METHODS REMOVED - Using the first implementation above

    @on(Action.MeterValues)
    async def on_meter_value(self, connector_id, meter_value, transaction_id=None, **kwargs):
        from .models import Transaction, MeterValue, Station
        
        print(f"MeterValues received: connector={connector_id}, transaction={transaction_id}")
        print(f"Raw meter_value data: {meter_value}")
        
        # Get station information for intelligent defaults
        station_info = await database_sync_to_async(
            lambda: Station.objects.filter(id=self.station_id).values(
                'connector_type', 'power_output', 'address'
            ).first()
        )()
        
        # Determine intelligent defaults based on station info
        is_dc_charger = 'DC' in str(station_info.get('connector_type', '')).upper() or station_info.get('power_output', 0) > 50
        power_output = station_info.get('power_output', 22)
        
        # Set defaults based on station characteristics
        default_measurand = 'Energy.Active.Import.Register'  # Default for AC charging
        if is_dc_charger:
            default_measurand = 'Energy.Active.Import.Register'  # Could be different for DC
        
        default_unit = 'Wh'  # Default unit
        
        print(f"Station info: {station_info}, is_dc_charger: {is_dc_charger}")
        
        # Save meter values to database if transaction exists
        if transaction_id:
            async def save_meter_values():
                try:
                    transaction = await database_sync_to_async(
                        Transaction.objects.get
                    )(id=transaction_id)
                    print(f"Found transaction {transaction_id}")

                    # Ensure aggregate MeterValue exists
                    def get_or_create_mv():
                        mv, created = MeterValue.objects.get_or_create(
                            transaction=transaction,
                            defaults={
                                "value": transaction.meter_start,
                                "data": {"start": {"meter_start": transaction.meter_start}, "samples": []},
                            },
                        )
                        return mv, created

                    mv, created = await database_sync_to_async(get_or_create_mv)()

                    # Append sampled values to mv.data["samples"]
                    data = mv.data or {}
                    samples = data.get("samples") or []
                    saved_count = 0
                    for sample in meter_value:
                        print(f"   Processing sample: {sample}")
                        sampled_values = sample.get('sampled_value', [])
                        print(f"   Found {len(sampled_values)} sampled_value(s)")
                        parent_ts = sample.get('timestamp')
                        for sv in sampled_values:
                            value = sv.get('value')
                            print(f"   Sampled value: {sv}, extracted value: {value}")
                            if value is None:
                                continue
                            enriched_sv = {
                                'value': sv.get('value'),
                                'context': sv.get('context', 'Sample.Periodic'),
                                'format': sv.get('format', 'Raw'),
                                'measurand': sv.get('measurand', default_measurand),
                                'phase': sv.get('phase', 'L1' if not is_dc_charger else 'L1'),
                                'location': sv.get('location', 'Outlet'),
                                'unit': sv.get('unit', default_unit),
                                'timestamp': parent_ts,
                            }
                            samples.append(enriched_sv)
                            saved_count += 1

                    data["samples"] = samples
                    mv.data = data
                    await database_sync_to_async(mv.save)()

                    if saved_count == 0:
                        print(f"No meter values were saved (data structure might be different)")
                    else:
                        print(f"Total saved: {saved_count} sampled_value(s) appended to aggregate record")

                except Transaction.DoesNotExist:
                    print(f"Transaction {transaction_id} not found in database")
                except Exception as e:
                    print(f"Error saving meter values: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
            
            await save_meter_values()
        else:
            print(f"No transaction_id provided, skipping save")
        
        return call_result.MeterValuesPayload()


    @on(Action.SecurityEventNotification)
    async def on_security_event_notification(self, type: str, timestamp: str, tech_info: str | None = None, **kwargs):
        """
        Handle SecurityEventNotification from the station (OCPP 1.6 Security extension).
        Minimal implementation: log and acknowledge.
        """
        try:
            print(
                f"SecurityEventNotification received: type={type}, timestamp={timestamp}, tech_info={tech_info}, extra={kwargs}"
            )
        except Exception as e:
            # Ensure we always ack even if logging fails
            print(f"Error logging SecurityEventNotification: {e}")

        # Acknowledge receipt per OCPP spec with an empty payload
        return call_result.SecurityEventNotificationPayload()

    @on(Action.Authorize)
    async def on_authorize(self, id_tag, **kwargs):
        from .models import UserRFID

        # Check if RFID tag exists, is active, and is assigned to this station
        async def check_rfid():
            try:
                # UserRFID has ManyToMany 'stations' field, so use stations__id for lookup
                return await database_sync_to_async(
                    lambda: UserRFID.objects.filter(
                        tag=id_tag,
                        stations__id=self.station_id,
                        is_active=True
                    ).exists()
                )()
            except Exception as e:
                print(f"Error checking RFID: {e}")
                return False

        is_valid = await check_rfid()
        status = AuthorizationStatus.accepted if is_valid else AuthorizationStatus.invalid
        
        # Clean, professional authorization logging
        print("\n=== OCPP 1.6 Authorize ===")
        print(f"Station ID: {getattr(self, 'station_id', 'N/A')}")
        print(f"RFID Tag: {id_tag}")
        print(f"Authorization: {'GRANTED' if is_valid else 'DENIED'}")
        if not is_valid:
            print("Reason: Invalid or unauthorized RFID tag")
        print()  # Add spacing

        # Return the authorization result
        return call_result.AuthorizePayload(
            id_tag_info={"status": status}
        )

    
    @on(Action.StartTransaction)
    async def on_start_transaction(self, connector_id, id_tag, timestamp, meter_start, **kwargs):
        try:
            # Validate RFID tag before starting a transaction
            is_valid_tag = await database_sync_to_async(
                lambda: UserRFID.objects.filter(tag=id_tag).exists()
            )()

            if not is_valid_tag:
                print(f"StartTransaction rejected: invalid id_tag={id_tag}")
                return call_result.StartTransactionPayload(
                    transaction_id=0,
                    id_tag_info={"status": AuthorizationStatus.invalid.value}
                )
            
            print(f"StartTransaction: connector={connector_id}, id_tag={id_tag}")

            # Get requested power from pending requests
            key = (connector_id, id_tag)
            requested_power = self.pending_requested_power.get(key, None)
            
            # Wrap entire atomic operation in database_sync_to_async
            @database_sync_to_async
            def create_transaction_atomic():
                with db_transaction.atomic():
                    # Get or create connector
                    connector, _ = Connector.objects.select_related("station").get_or_create(
                        station_id=self.station_id,
                        connector_id=connector_id,
                        defaults={"status": "available"}
                    )

                    # Create transaction
                    transaction = Transaction.objects.create(
                        connector=connector,
                        id_tag=id_tag,
                        meter_start=meter_start,
                        requested_power_kw=requested_power,
                        status="active"
                    )

                    # Create initial meter value
                    MeterValue.objects.create(
                        transaction=transaction,
                        value=meter_start,
                        data={
                            "start": {
                                "ocpp_timestamp": str(timestamp),
                                "meter_start": meter_start,
                            },
                            "samples": [],
                        }
                    )

                    # Update connector status
                    connector.status = "charging"
                    connector.save()

                    return connector, transaction

            async with self.db_lock:
                connector, transaction = await create_transaction_atomic()

            # Clear pending power
            key = (connector_id, id_tag)
            if key in self.pending_requested_power:
                del self.pending_requested_power[key]

            # Update station status and broadcast to clients
            await self._update_station_status_async('active', 'start')
            
            # Broadcast connector status change to all connected browsers
            if hasattr(self, 'consumer') and self.consumer:
                try:
                    await self.consumer.channel_layer.group_send(
                        self.consumer.group_name,
                        {
                            "type": "station_message",
                            "message": json.dumps({
                                "type": "connector_status_update",
                                "station_id": str(self.station_id),
                                "connector_id": connector_id,
                                "connector_status": "charging",
                                "status": "active",
                                "transaction_id": transaction.id,
                                "timestamp": timezone.now().isoformat()
                            })
                        }
                    )
                except Exception as e:
                    print(f"Error broadcasting connector status: {e}")
                    # Continue without broadcasting to avoid disconnect

            print(f"Transaction {transaction.id} started on connector {connector_id}")

            return call_result.StartTransactionPayload(
                transaction_id=transaction.id,
                id_tag_info={"status": AuthorizationStatus.accepted.value}
            )

        except Exception as e:
            print(f"Error in on_start_transaction: {e}")
            import traceback
            traceback.print_exc()
            return call_result.StartTransactionPayload(
                transaction_id=0,
                id_tag_info={"status": AuthorizationStatus.invalid.value}
            )


    @on(Action.StopTransaction)
    async def on_stop_transaction(self, transaction_id, id_tag, timestamp, meter_stop, reason, **kwargs):
        from .models import Transaction, Connector, MeterValue

        print(f"StopTransaction received: transaction_id={transaction_id}, id_tag={id_tag}, meter_stop={meter_stop}, reason={reason}")

        # Validate and normalize reason
        valid_reasons = {
            "EmergencyStop", "EVDisconnected", "HardReset",
            "Local", "Other", "PowerLoss", "Reboot", "Remote", "SoftReset"
        }
        safe_reason = reason if reason in valid_reasons else "Other"

        response = call_result.StopTransactionPayload(
            id_tag_info={"status": AuthorizationStatus.accepted.value}
        )

        # Function to stop transaction and update connector in atomic operation
        def stop_transaction():
            with db_transaction.atomic():
                # Use select_for_update to prevent race conditions
                transaction_obj = (
                    Transaction.objects
                    .select_related("connector__station")
                    .select_for_update()
                    .get(id=transaction_id)
                )
                
                # Validate transaction belongs to this station
                if transaction_obj.connector.station_id != self.station_id:
                    print(f"Transaction {transaction_id} does not belong to station {self.station_id}")
                    return None
                
                # Check if already completed to avoid duplicate processing
                if transaction_obj.status == "completed":
                    print(f"Transaction {transaction_id} already completed, skipping")
                    return None
                
                transaction_obj.meter_stop = meter_stop
                transaction_obj.stopped_at = timezone.now()
                transaction_obj.status = "completed"
                transaction_obj.save()

                # Update connector status in the same atomic transaction
                connector = transaction_obj.connector
                connector.status = "available"
                connector.save()

                # Create final MeterValue record (don't overwrite historical data)
                try:
                    MeterValue.objects.create(
                        transaction=transaction_obj,
                        value=meter_stop,
                        data={
                            "type": "final",
                            "ocpp_timestamp": str(timestamp),
                            "meter_start": transaction_obj.meter_start,
                            "meter_stop": meter_stop,
                            "reason": reason or "",
                        },
                    )
                except Exception as e:
                    # Best-effort: do not block completion if meter value update fails
                    print(f"Failed to persist final meter data for transaction {transaction_id}: {e}")

                return transaction_obj.connector.station.id

        try:
            station_id = await database_sync_to_async(stop_transaction)()
            if not station_id:
                return response
        except Transaction.DoesNotExist:
            print(f"Transaction {transaction_id} does not exist!")
            return response

        # Broadcast status updates via WebSocket
        if getattr(self, "consumer", None):
            await self.consumer.update_station_status(station_id, "active", "stop")
            # Broadcast connector and transaction status change
            await self.consumer.channel_layer.group_send(
                self.consumer.group_name,
                {
                    "type": "station_message",
                    "message": json.dumps({
                        "type": "transaction_stopped",
                        "station_id": str(station_id),
                        "transaction_id": transaction_id,
                        "connector_status": "available",
                        "timestamp": timezone.now().isoformat()
                    })
                }
            )

        print(f"Transaction {transaction_id} stopped successfully")
        return response
    

    # REMOVED: call_heartbeat() - Central System must NEVER send Heartbeat.req
    # Only Charge Points should send Heartbeat to Central System
    
    async def call_authorize(self, id_tag):
        """Platform requests authorization for an RFID tag"""
        req = call.Authorize(id_tag=id_tag)
        return await self.call(req)
    
    async def call_remote_start_transaction(self, connector_id, id_tag, requested_power=None):
        """Platform remotely starts charging on the station"""
        # Store requested power for when StartTransaction notification arrives
        self.pending_requested_power[(connector_id, id_tag)] = requested_power
        
        charging_profile = None
        
        # Create ChargingProfile to actually control station output power
        if requested_power:
            charging_profile = {
                "chargingProfileId": 1,
                "stackLevel": 0,
                "chargingProfilePurpose": "TxProfile",  # Transaction-specific profile
                "chargingProfileKind": "Relative",      # Relative to start of charging
                "chargingSchedule": {
                    "chargingRateUnit": "W",            # Watts
                    "chargingSchedulePeriod": [
                        {
                            "startPeriod": 0,           # Start immediately
                            "limit": requested_power * 1000  # Convert kW to W
                        }
                    ]
                }
            }
            print(f"Sending power limit to station: {requested_power} kW ({requested_power * 1000} W)")
        
        req = call.RemoteStartTransactionPayload(
            connector_id=connector_id,
            id_tag=id_tag,
            charging_profile=charging_profile
        )
        return await self.call(req)
    
    async def call_remote_stop_transaction(self, transaction_id):
        """Platform remotely stops charging on the station"""
        req = call.RemoteStopTransactionPayload(
            transaction_id=transaction_id
        )
        return await self.call(req)
    
    async def call_change_availability(self, connector_id, availability_type):
        """Platform changes station/connector availability (Operative/Inoperative)"""
        req = call.ChangeAvailabilityPayload(
            connector_id=connector_id,
            type=availability_type  # "Operative" or "Inoperative"
        )
        print(f"Changing availability for connector {connector_id} to {availability_type}")
        return await self.call(req)
    
    async def call_reset(self, reset_type="Soft"):
        """Platform resets the station (Soft or Hard)"""
        req = call.ResetPayload(
            type=reset_type  # "Soft" or "Hard"
        )
        print(f"Sending {reset_type} reset to station")
        return await self.call(req)
    
    async def call_unlock_connector(self, connector_id):
        """Platform unlocks a connector"""
        req = call.UnlockConnectorPayload(
            connector_id=connector_id
        )
        print(f"Unlocking connector {connector_id}")
        return await self.call(req)
    
    async def call_get_configuration(self, keys=None):
        """Platform retrieves station configuration"""
        req = call.GetConfigurationPayload(
            key=keys  # None = get all keys
        )
        print(f"Getting configuration from station")
        return await self.call(req)
    
    # REMOVED: call_get_meter_values() - MeterValues is CP → CS only
    # There is NO request called MeterValues.req in OCPP 1.6
    # Use GetCompositeSchedule or wait for periodic MeterValues
    

# -------------------------
# Channels WebSocket Consumer
# -------------------------
    class ChargePointConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_lock = asyncio.Lock()  # Lock за всички записи към SQLite
        self._is_closing = False  # Guard to prevent sends while closing
        self._connected = False   # Track websocket connection state

    @database_sync_to_async
    def station_exists(self, station_id):
        from .models import Station
        return Station.objects.filter(id=station_id).exists()


    async def connect(self):
        # Get station_id from URL parameters and convert to int for consistent key type
        self.station_id = int(self.scope['url_route']['kwargs']['station_id'])
        
        # Get serial_number if it exists
        self._connected = True
        self._is_closing = False
        
        print(f"Station {self.station_id} (Serial: None) connecting...")
        
        try:
            # Accept the WebSocket connection with ping/pong
            await self.accept(subprotocol="ocpp1.6")
            print("Accepted connection from station")
            
            # Create WebSocket wrapper for OCPP communication
            self.ws_wrapper = WebSocketWrapper(self)
            
            # Initialize ChargePoint with the wrapper
            self.cp = ChargePoint(self.station_id, self.ws_wrapper, self)
            self.cp_task = asyncio.create_task(self.cp.start())
            # Start liveness watchdog to detect unexpected power-off
            self.watchdog_task = asyncio.create_task(self.liveness_watchdog())
            
            # Add to channel group
            self.group_name = "charging_stations_group"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            
            # Register this consumer in the global registry
            register_station(self.station_id, self)
            print(f"Station {self.station_id} fully initialized and registered")
            
        except Exception as e:
            print(f"Error during station initialization: {e}")
            await self.close(code=1011)  # Internal error


    async def disconnect(self, close_code):
        # FIRST: Broadcast station offline immediately (before any cleanup)
        await self.broadcast_station_offline()
        
        # THEN: Update database and other status updates
        try:
            if hasattr(self, 'station_id') and hasattr(self, 'channel_layer'):
                # Update database and broadcast disconnect status
                await self.update_station_status(self.station_id, "inactive", "disconnect")
                
                # Update all connectors for this station to offline
                from .models import Connector
                if hasattr(self, 'db_lock'):
                    async with self.db_lock:
                        await database_sync_to_async(
                            lambda: Connector.objects.filter(station_id=self.station_id).update(status="offline")
                        )()
                
                print(f"Station {self.station_id} disconnected")
        except Exception as e:
            print(f"Error updating statuses on disconnect: {e}")
        
        # FINALLY: Mark as closing to prevent further sends
        self._is_closing = True
        self._connected = False
        
        # Cancel the ChargePoint task
        if hasattr(self, 'cp_task'):
            self.cp_task.cancel()
            try:
                await self.cp_task
            except asyncio.CancelledError:
                pass
        
        # Cancel liveness watchdog
        if hasattr(self, 'watchdog_task'):
            self.watchdog_task.cancel()
            try:
                await self.watchdog_task
            except asyncio.CancelledError:
                pass
        
        # Remove from channel group AFTER broadcasting
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        
        # Unregister from global registry (already cleans up ACTIVE_STATIONS and _last_heartbeat_log)
        if hasattr(self, 'station_id') and self.station_id in ACTIVE_STATIONS:
            unregister_station(self.station_id)
        else:
            # Ensure cleanup even if not in ACTIVE_STATIONS
            if hasattr(self, 'station_id'):
                ACTIVE_STATIONS.pop(self.station_id, None)
                _last_heartbeat_log.pop(self.station_id, None)


    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            # Check for WebSocket ping/pong frames
            if bytes_data:
                # WebSocket ping/pong frames are handled by the server automatically
                # We don't need to process them here
                return
            return

        # Ensure ws_wrapper is initialized
        if not hasattr(self, 'ws_wrapper'):
            print("Warning: Received message before WebSocket wrapper was initialized")
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            # Check if this is a WebSocket ping (not JSON)
            if text_data.strip() == "ping" or text_data.strip() == "PING":
                # Respond with pong
                await self.send(text_data="pong")
                # Skip logging to reduce spam
                return
            print(f"[receive] Invalid JSON received: {text_data}")
            return

        # All OCPP messages (dict or list) are forwarded to the ChargePoint
        if isinstance(data, (dict, list)):
            try:
                await self.ws_wrapper.feed(text_data)
            except Exception as e:
                print(f"Error forwarding message to ChargePoint: {e}")
        else:
            print(f"[receive] Unexpected data type: {type(data)} - {data}") 


    async def broadcast_status_update(self, status, action):
        try:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "station_message",
                    "message": json.dumps({
                        "type": "station_status_update",
                        "station_id": str(self.station_id),
                        "status": status,
                        "action": action
                    })
                }
            )
        except Exception as e:
            print(f"Error in broadcast_status_update: {e}")
            # Continue without broadcasting to avoid disconnect

    @database_sync_to_async
    def _get_station(self, station_id):
        from .models import Station
        return Station.objects.get(id=station_id)
    
    @database_sync_to_async
    def _save_station(self, station):
        station.save()
        return station
    
    async def update_station_status(self, station_id, status, reason=""):
        """Update station status in the database and broadcast to all connected clients."""
        try:
            # Get the station using the async helper
            station = await self._get_station(station_id)
            if not station:
                print(f"Station {station_id} not found")
                return False

            async with self.db_lock:
                old_status = station.status
                station.status = status
                station.last_seen = timezone.now()
                
                # Save using the async helper
                await self._save_station(station)
                
                print(f"Station {station_id} status updated: {old_status} -> {status} (Reason: {reason})")
                
                # Broadcast the status update to all connected clients
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "station_message",
                        "message": json.dumps({
                            "type": "status_update",
                            "station_id": str(station_id),
                            "status": status,
                            "reason": reason,
                            "timestamp": timezone.now().isoformat()
                        })
                    }
                )
                    
                # Also refresh the station table in the UI
                await self.broadcast_station_table()
                
                return True
        except Exception as e:
            print(f"Error updating station status: {e}")
            import traceback
            traceback.print_exc()
            return False

    # REMOVED: station_message from ChargePointConsumer
    # ChargePointConsumer should only emit messages, not handle UI events
    # StationStatusConsumer handles all station_message events

    async def broadcast_connector_status(self, station_id, connector_status):
        """Broadcast connector status change to all connected browsers"""
        from .models import Connector, Transaction
        
        # Get the connector from the database
        connector = await database_sync_to_async(
            lambda: Connector.objects.filter(station_id=station_id).first()
        )()
        
        if not connector:
            # No connector record yet, create a default one
            connector = await database_sync_to_async(Connector.objects.create)(
                station_id=station_id,
                connector_id=1,  # Default to connector 1 if none exists
                status=connector_status
            )
        
        # Update connector status to the requested status
        old_connector_status = connector.status
        connector.status = connector_status
        await database_sync_to_async(connector.save)()
        print(f"Connector {connector.connector_id} status updated: {old_connector_status} -> {connector_status}")
        
        # Clean up any stale "active" transactions if going offline
        if connector_status == "offline":
            stale_transactions = await database_sync_to_async(
                lambda: list(Transaction.objects.filter(
                    connector=connector,
                    status="active"
                ))
            )()
            
            if stale_transactions:
                print(f"Cleaning up {len(stale_transactions)} stale transaction(s)")
                for txn in stale_transactions:
                    txn.status = "stopped"
                    await database_sync_to_async(txn.save)()
        
        # Determine station status based on connector status
        station_status = "inactive" if connector_status == "offline" else "active"
        
        # Broadcast connector status update
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "station_message",
                "message": json.dumps({
                    "type": "connector_status_update",
                    "station_id": str(station_id),
                    "connector_status": connector_status,
                    "status": station_status,
                    "connector_id": connector.connector_id if connector else 1
                })
            }
        )


    @database_sync_to_async
    def _get_stations(self):
        from .models import Station
        return list(Station.objects.all().prefetch_related('connectors'))

    @database_sync_to_async
    def _render_station_table(self, stations):
        from django.template.loader import render_to_string
        from django.template import RequestContext
        from django.http import HttpRequest
        
        # Create a basic request to ensure CSRF token is available if needed
        request = HttpRequest()
        request.META['SERVER_NAME'] = 'localhost'
        request.META['SERVER_PORT'] = '8000'
        
        return render_to_string(
            "charging_stations/_stations_tab.html", 
            {"stations_list": stations},
            request=request
        )

    async def broadcast_station_table(self):
        """Broadcast updated station table HTML to all connected clients"""
        try:
            # Get stations asynchronously with related data
            stations = await self._get_stations()
            
            # Render template asynchronously
            html = await self._render_station_table(stations)
            
            # Broadcast to all connected clients
            if hasattr(self, 'channel_layer') and hasattr(self, 'group_name'):
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "station_message",
                        "message": json.dumps({
                            "type": "station_table_update",
                            "html": html
                        }, cls=DjangoJSONEncoder)
                    }
                )
        except Exception as e:
            print(f"Error broadcasting station table: {e}")
            import traceback
            traceback.print_exc()

    # DUPLICATE REMOVED - Using the first station_message implementation above

    async def broadcast_station_offline(self):
        """Broadcast station offline status immediately on disconnect."""
        try:
            await self.channel_layer.group_send(
                "charging_stations_group",
                {
                    "type": "station_message",
                    "message": json.dumps({
                        "type": "station_offline",
                        "station_id": str(self.station_id),
                        "status": "inactive",
                        "connector_status": "offline",
                        "timestamp": timezone.now().isoformat()
                    })
                }
            )
            print(f"[BROADCAST] Station {self.station_id} offline message sent")
        except Exception as e:
            print(f"[BROADCAST] Error sending station offline: {e}")
            # Never block disconnect

    async def liveness_watchdog(self):
        """Mark station inactive/offline if no heartbeats/messages within timeout."""
        try:
            while True:
                await asyncio.sleep(5)
                if not hasattr(self, 'cp'):
                    continue
                now = datetime.now().astimezone()
                interval = getattr(self.cp, 'heartbeat_interval', 60)
                # Use 10x heartbeat interval with minimum 300 seconds to avoid premature timeouts
                timeout_seconds = max(300, interval * 10)
                if (now - self.cp.last_seen) > timedelta(seconds=timeout_seconds):
                    print(f"Watchdog timeout for station {self.station_id}: marking inactive/offline")
                    # Broadcast offline immediately
                    await self.broadcast_station_offline()
                    await self.update_station_status(self.station_id, "inactive", "timeout")
                    from .models import Connector, Transaction, MeterValue
                    async with self.db_lock:
                        #Finalize any active transactions for this station
                        def finalize_station_transactions():
                            active_txs = (
                                Transaction.objects
                                .filter(connector__station_id=self.station_id, status="active")
                            )
                            for tx in active_txs:
                                last_mv = (
                                    MeterValue.objects
                                    .filter(transaction=tx)
                                    .order_by("-timestamp")
                                    .first()
                                )
                                if last_mv:
                                    tx.meter_stop = last_mv.value
                                tx.stopped_at = datetime.now().astimezone()
                                tx.status = "error"
                                tx.save()
                        await database_sync_to_async(finalize_station_transactions)()
                        await database_sync_to_async(
                            lambda: Connector.objects.filter(station_id=self.station_id).update(status="offline")
                        )()
                    await self.broadcast_connector_status(self.station_id, "offline")
                    # Close the socket last, and mark closing to prevent race on sends
                    self._is_closing = True
                    try:
                        await self.close()
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            # Normal on disconnect
            return


    # DUPLICATE REMOVED - Using the first station_message implementation above


# -------------------------
# Station Status Consumer for Browser Clients
# -------------------------
    class StationStatusConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for browser clients to receive real-time station status updates.
    Browsers connect to this endpoint (not the OCPP endpoint).
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = "status_updates"  # Default group name
    
    # StationStatusConsumer needs to handle station_message events
    async def station_message(self, event):
        """Handle messages from charging_stations_group for browser clients."""
        if getattr(self, "_is_closing", False):
            return

        message = event.get("message")
        if not message:
            return

        try:
            await self.send(text_data=message)
        except Exception:
            pass
    
    @database_sync_to_async
    def get_station_status(self):
        """Fetch current status of all stations and active charging sessions"""
        from .models import Station, Connector, Transaction
        from django.db.models import Sum, Q
        from django.utils import timezone
        from datetime import datetime, time, timedelta
        
        try:
            # Get current time and today's date range
            now = timezone.now()
            today_start = timezone.make_aware(datetime.combine(now.date(), time.min))
            
            # Get all stations and their status using the correct related_name 'connectors'
            stations = list(Station.objects.all().prefetch_related('connectors'))
            total_stations = len(stations)
            # Count online stations based on actual WebSocket connections, not DB status
            online_stations = sum(1 for s in stations if s.id in ACTIVE_STATIONS)
            
            # Debug: Log ACTIVE_STATIONS content
            print(f"[DEBUG] ACTIVE_STATIONS: {list(ACTIVE_STATIONS.keys())}")
            print(f"[DEBUG] Station IDs in DB: {[s.id for s in stations]}")
            print(f"[DEBUG] Online stations: {online_stations}/{total_stations}")
            
            # Get all connectors and their status
            connectors = Connector.objects.filter(station__in=stations)
            available_connectors = connectors.filter(status='available').count()
            
            # Get active charging sessions
            active_sessions = connectors.filter(status='charging').count()
            
            # Calculate total energy delivered today
            today_energy = Transaction.objects.filter(
                started_at__date=now.date()
            ).aggregate(total=Sum('meter_stop'))['total'] or 0
            
            # Convert to kWh if needed (assuming meter values are in Wh)
            today_energy_kwh = float(today_energy) / 1000.0 if today_energy else 0.0
            
            # Get total sessions today
            total_sessions_today = Transaction.objects.filter(
                started_at__date=now.date()
            ).count()
            
            # Get active charging sessions with details
            active_charging_sessions = []
            active_transactions = Transaction.objects.filter(
                stopped_at__isnull=True
            ).select_related('connector', 'connector__station')
            
            for txn in active_transactions:
                duration = now - txn.started_at if txn.started_at else timedelta(0)
                hours, remainder = divmod(duration.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                
                # Calculate energy delivered in kWh
                energy_delivered = 0
                if txn.meter_start is not None and txn.meter_stop is not None:
                    energy_delivered = (txn.meter_stop - txn.meter_start) / 1000.0  # Convert to kWh
                elif txn.meter_start is not None:
                    # For active sessions, we don't have meter_stop yet
                    energy_delivered = 0
                
                active_charging_sessions.append({
                    'station_id': txn.connector.station.id,
                    'station_name': txn.connector.station.formatted_serial(),
                    'connector_id': txn.connector.connector_id,
                    'id_tag': txn.id_tag,
                    'start_time': txn.started_at.isoformat() if txn.started_at else now.isoformat(),
                    'energy_delivered': energy_delivered,
                    'duration': f"{hours:02d}:{minutes:02d}",
                    'status': txn.status.capitalize(),
                    'power': txn.requested_power_kw or 0
                })
            
            # Get recent alerts/notifications (last 24 hours)
            recent_alerts = []  # You can implement this based on your alert system
            
            return {
                'success': True,
                'station_count': total_stations,
                'online_count': online_stations,
                'available_count': available_connectors,
                'active_sessions': active_sessions,
                'energy_delivered': today_energy_kwh,
                'total_sessions': total_sessions_today,
                'active_charging_sessions': active_charging_sessions,
                'last_updated': timezone.now().isoformat(),
                'recent_alerts': recent_alerts,
                'status': 'success'
            }
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"Error in get_station_status: {error_msg}")
            traceback.print_exc()
            
            # Return error response
            return {
                'success': False,
                'error': error_msg,
                'status': 'error',
                'station_count': 0,
                'online_count': 0,
                'available_count': 0,
                'active_sessions': 0,
                'energy_delivered': 0.0,
                'total_sessions': 0,
                'active_charging_sessions': [],
                'last_updated': timezone.now().isoformat()
            }
    
    async def connect(self):
        """Handle new WebSocket connection."""
        try:
            station_id = self.scope['url_route']['kwargs'].get('station_id')
            
            if station_id:
                # If station_id is provided, add to station-specific group
                station_group = f"station_{station_id}"
                await self.channel_layer.group_add(
                    station_group,
                    self.channel_name
                )
                self.group_name = station_group
            
            # Always add to global status group
            await self.channel_layer.group_add(
                "status_updates",
                self.channel_name
            )
            
            # Also join the charging_stations_group to receive station updates
            await self.channel_layer.group_add(
                "charging_stations_group",
                self.channel_name
            )
            
            await self.accept()
            self._connected = True
            await self.send_initial_status()
            
        except Exception as e:
            print(f"Error in StationStatusConsumer.connect: {e}")
            await self.close()

    async def disconnect(self, close_code):
        try:
            # Leave the broadcast group if group_name is set
            if hasattr(self, 'group_name'):
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
                
            # Remove from the global status group
            await self.channel_layer.group_discard(
                "status_updates",
                self.channel_name
            )
            
            # Remove from charging_stations_group
            await self.channel_layer.group_discard(
                "charging_stations_group",
                self.channel_name
            )
                
            print(f"Browser client disconnected from status updates")
        except Exception as e:
            print(f"Error in StationStatusConsumer.disconnect: {e}")
    
    # DUPLICATE REMOVED - station_message already defined above

    async def receive(self, text_data=None):
        """Handle incoming WebSocket messages from the client"""
        if not text_data:
            return
            
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'get_initial_data':
                # Client is requesting fresh data
                await self.send_initial_status()
                
        except json.JSONDecodeError:
            print(f"Received invalid JSON: {text_data}")
        except Exception as e:
            print(f"Error processing WebSocket message: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_initial_status(self):
        """Send the current status of all stations to the client"""
        try:
            status_data = await self.get_station_status()
            await self.send(text_data=json.dumps({
                'type': 'status_update',
                'data': status_data,
                'timestamp': timezone.now().isoformat()
            }))
            # Also send individual station status updates for each connected station
            # This ensures the frontend UI updates correctly
            for station_id in ACTIVE_STATIONS.keys():
                # Get connector status for this station
                connector_status = await database_sync_to_async(
                    lambda sid=station_id: Connector.objects.filter(station_id=sid).values_list('status', flat=True).first() or 'available'
                )()
                
                await self.send(text_data=json.dumps({
                    'type': 'connector_status_update',
                    'station_id': str(station_id),
                    'status': 'active',
                    'connector_status': connector_status,
                    'timestamp': timezone.now().isoformat()
                }))
                
        except Exception as e:
            print(f"Error sending initial status: {e}")
            import traceback
            traceback.print_exc()
    
    # DUPLICATE REMOVED - Using the first station_message implementation above
            # The frontend JavaScript will handle the different message types
            if message_data:
                await self.send(text_data=json.dumps(message_data))
                
        except Exception as e:
            print(f"Error in station_message: {e}")
            import traceback
            traceback.print_exc()