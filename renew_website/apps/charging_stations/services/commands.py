from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from ..consumers import ACTIVE_STATIONS
from ..models import UserRFID, Transaction, Connector, Station

def execute_station_action(action: str, station_ids: list, power: str = None) -> tuple[int, int, str]:
    """
    Executes an action (start/stop) on a list of stations.
    Returns a tuple of (success_count, error_count, message).
    """
    if not station_ids:
        return 0, 0, "No station selected."
        
    valid_rfid = UserRFID.objects.filter(tag="000000010160897").first()
    if not valid_rfid:
        valid_rfid = UserRFID.objects.create(
            tag="000000010160897",
            owner_name="Default Test Tag"
        )

    results = []
    success_count = 0
    error_count = 0
    channel_layer = get_channel_layer()

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
                if power and power.lower() == 'auto':
                    power_limit = None
                elif power:
                    power_limit = int(power)
                else:
                    station = Station.objects.get(id=station_id)
                    power_limit = station.power_output

                message = {
                    "type": "remote_start_transaction",
                    "connector_id": connector.connector_id,
                    "id_tag": valid_rfid.tag,
                    "requested_power": power_limit,
                    "station_id": station_id,
                }
                
                async_to_sync(channel_layer.group_send)(
                    f"charging_stations_group_{station_id}",
                    message
                )
                
                results.append(f"Station {station_id}: RemoteStartTransaction sent successfully")
                success_count += 1
                
            elif action == "stop":
                active_transaction = Transaction.objects.filter(
                    connector__station_id=station_id,
                    status="active"
                ).first()
                
                if active_transaction:
                    message = {
                        "type": "remote_stop_transaction",
                        "transaction_id": active_transaction.id,
                        "station_id": station_id,
                    }
                    
                    async_to_sync(channel_layer.group_send)(
                        f"charging_stations_group_{station_id}",
                        message
                    )
                    
                    results.append(f"Station {station_id}: Stop command sent")
                    success_count += 1
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
