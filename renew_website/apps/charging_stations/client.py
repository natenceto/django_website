import asyncio
import json
import websockets
import os
import sys

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "renew_website.settings")
import django
django.setup()

from renew_website.apps.charging_stations.models import Station
from channels.db import database_sync_to_async

# OCPP imports
from ocpp.v16 import call, call_result
from datetime import datetime

# ------------------------
# WebSocket client per station
# ------------------------
async def run_client_for_station(station_id):
    # Check
    exists = await get_station_exists(station_id)
    if not exists:
        print(f"Station {station_id} does not exist. Connection closed.")
        return

    # Fixed configuration: Always use ws:// for simplicity and reliability
    server_host = os.getenv('OCPP_SERVER_HOST', '192.168.88.243')
    server_port = os.getenv('OCPP_SERVER_PORT', '8000')
    
    # Always use ws:// - works for both testing and production
    url = f"ws://{server_host}:{server_port}/ws/charging_stations/{station_id}/"
    
    print(f"Connecting to station {station_id} at {url}")
    try:
        async with websockets.connect(url, subprotocols=["OCPP1.6"]) as ws:
            print(f"Connected to station ID: {station_id}")

            # Send BootNotification
            boot_msg = call.BootNotificationPayload(
                charge_point_model="AVT-Express",
                charge_point_vendor="AVT-Company",
                charge_point_serial_number="avt.001.13.1",
                charge_box_serial_number="avt.001.13.1.01",
                firmware_version="1.8.37",
                iccid="",
                imsi="",
                meter_type="AVT NQC-ACDC",
                meter_serial_number="avt.001.13.1.01",
            ).to_json()
            await ws.send(boot_msg)
            print(f"Sent BootNotification for station ID: {station_id}")

            # Wait for response
            response = await ws.recv()
            print(f"Received response: {response}")

            # Send Heartbeat periodically and listen for responses
            heartbeat_count = 0
            while True:
                heartbeat_msg = call.HeartbeatPayload().to_json()
                await ws.send(heartbeat_msg)
                print(f"Sent Heartbeat #{heartbeat_count} for station ID: {station_id}")
                
                # Listen for server messages
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    print(f"Received server message: {response}")
                except asyncio.TimeoutError:
                    print("No response from server (timeout)")
                
                heartbeat_count += 1
                await asyncio.sleep(10)

    except Exception as e:
        print(f"Error for station ID: {station_id}: {e}")

@database_sync_to_async
def get_station_exists(station_id):
    from renew_website.apps.charging_stations.models import Station
    return Station.objects.filter(id=station_id).exists()


# ------------------------
# Main async runner
# ------------------------
async def main():
    stations = await get_stations()
    if not stations:
        print("No stations found in database.")
        return

    tasks = [run_client_for_station(station.id) for station in stations]
    await asyncio.gather(*tasks)

@database_sync_to_async
def get_stations():
    return list(Station.objects.all())

if __name__ == "__main__":
    asyncio.run(main())