from .ocpp_command_bus import CommandDispatchError, StartChargingCommand, StopChargingCommand, command_bus
from ..models import UserRFID, Transaction, Connector, Station
from ..tasks import send_to_ui


DEFAULT_TEST_RFID_TAG = "000000010160897"


def _format_requested_power_display(requested_power_kw, requested_power_mode):
    if requested_power_mode == "auto" and requested_power_kw is None:
        return "Auto"
    if requested_power_kw is not None:
        return f"{float(requested_power_kw):.2f} kW"
    return "Station default"

def execute_station_action(action: str, station_ids: list, power: str = None) -> tuple[int, int, str]:
    """
    Executes an action (start/stop) on a list of stations.
    Returns a tuple of (success_count, error_count, message).
    """
    if not station_ids:
        return 0, 0, "No station selected."
        
    valid_rfid = UserRFID.objects.filter(tag=DEFAULT_TEST_RFID_TAG).first()
    if not valid_rfid:
        valid_rfid = UserRFID.objects.create(
            tag=DEFAULT_TEST_RFID_TAG,
            owner_name="Default Test Tag"
        )

    results = []
    success_count = 0
    error_count = 0
    for station_id in station_ids:
        station_id = int(station_id)
        
        try:
            if action == "start":
                connector = Connector.objects.filter(station_id=station_id, connector_id=1).first()
                if not connector:
                    results.append(f"Station {station_id}: Connector 1 not discovered yet. Wait for station boot/status to report connector 1.")
                    error_count += 1
                    continue
                
                power_limit = None
                power_mode = "station-default"
                if power and power.lower() == 'auto':
                    power_limit = None
                    power_mode = "auto"
                elif power:
                    power_limit = float(power)
                    power_mode = "manual"
                else:
                    station = Station.objects.get(id=station_id)
                    power_limit = station.power_output

                session_context = {
                    "command_source": "operator_ui",
                    "requested_power_mode": power_mode,
                    "session_source": "platform",
                    "runtime_type": "real",
                }

                try:
                    command_bus.dispatch(
                        StartChargingCommand(
                            station_id=station_id,
                            connector_id=connector.connector_id,
                            id_tag=valid_rfid.tag,
                            requested_power_kw=power_limit,
                            session_context=session_context,
                        )
                    )
                    send_to_ui({
                        "type": "station_power_update",
                        "station_id": station_id,
                        "requested_power_kw": power_limit,
                        "requested_power_mode": power_mode,
                        "requested_power_display": _format_requested_power_display(power_limit, power_mode),
                        "actual_power_kw": None,
                        "ems_limit_kw": None,
                        "energy_kwh": 0.0,
                    })
                    results.append(f"Station {station_id}: RemoteStartTransaction queued for station dispatch")
                    success_count += 1
                except CommandDispatchError as exc:
                    results.append(f"Station {station_id}: Failed to start charging - {str(exc)}")
                    error_count += 1
                
            elif action == "stop":
                active_transaction = Transaction.objects.filter(
                    connector__station_id=station_id,
                    status="active"
                ).first()
                
                if active_transaction:
                    try:
                        ocpp_transaction_id = active_transaction.transaction_id or active_transaction.id
                        command_bus.dispatch(
                            StopChargingCommand(
                                station_id=station_id,
                                transaction_id=ocpp_transaction_id,
                                connector_id=active_transaction.connector.connector_id if active_transaction.connector else 1,
                            )
                        )
                        send_to_ui({
                            "type": "connector_status_update",
                            "station_id": station_id,
                            "status": "active",
                            "connector_status": "finishing",
                        })
                        results.append(f"Station {station_id}: RemoteStopTransaction queued for station dispatch")
                        success_count += 1
                    except CommandDispatchError as exc:
                        results.append(f"Station {station_id}: Failed to stop charging - {str(exc)}")
                        error_count += 1
                else:
                    connector = Connector.objects.filter(station_id=station_id, connector_id=1).first()
                    connector_status = (connector.status if connector else "") or ""
                    preparing_like_statuses = {"preparing", "suspendedEV", "suspendedEVSE", "finishing"}

                    if connector_status in preparing_like_statuses:
                        try:
                            # Some chargers keep "Preparing" before StartTransaction is created.
                            # Send best-effort stop with transaction_id=0 to abort pending handshake.
                            command_bus.dispatch(
                                StopChargingCommand(
                                    station_id=station_id,
                                    transaction_id=0,
                                    connector_id=connector.connector_id if connector else 1,
                                )
                            )
                            results.append(
                                f"Station {station_id}: Abort requested for connector state '{connector_status}' (pending session without active transaction)."
                            )
                            success_count += 1
                        except CommandDispatchError as exc:
                            results.append(f"Station {station_id}: Failed to abort pending session - {str(exc)}")
                            error_count += 1
                    else:
                        results.append(f"Station {station_id}: No active charging session")
                        error_count += 1
            
            elif action == "apply_power":
                power_val = power or "11"
                results.append(f"Station {station_id}: Power set to {power_val} kW (not implemented)")
                success_count += 1
            
            else:
                results.append(f"Unknown action: {action}")
                error_count += 1
        
        except Exception as e:
            error_msg = str(e)
            if "Waited 30s for response" in error_msg or "timeout" in error_msg.lower():
                results.append(f"Station {station_id}: Command not supported by simulator/station")
            else:
                results.append(f"Station {station_id}: Error - {error_msg}")
            error_count += 1

    message = '<br>'.join(results)
    return success_count, error_count, message
