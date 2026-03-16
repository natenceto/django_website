"""
Energy data collection and management services.
"""
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction

from renew_website.apps.api.deye.client import DeyeCloudClient, DeyeCloudError
from .models import Inverter, InverterReading

logger = logging.getLogger(__name__)


class InverterDataService:
    """Service for collecting and managing inverter data."""
    
    def __init__(self):
        self.client = DeyeCloudClient()
        self.station_id = 61470379  # Your BAS Renew station
    
    def collect_current_data(self):
        """
        Collect current data from all inverters and store in database.
        This should be called periodically (e.g., every 5 minutes).
        """
        try:
            # Get station latest data (station-level metrics)
            station_data = self.client.get_station_latest(self.station_id)
            
            # Get station with devices to find inverters
            stations_with_devices = self.client.get_stations_with_devices()
            
            # Find our station
            station = None
            for s in stations_with_devices.get('stationList', []):
                if s['id'] == self.station_id:
                    station = s
                    break
            
            if not station:
                logger.error(f"Station {self.station_id} not found")
                return
            
            # Get inverter device SNs
            inverter_sns = []
            inverters_data = []
            for device in station.get('deviceListItems', []):
                if device['deviceType'] == 'INVERTER':
                    inverter_sns.append(device['deviceSn'])
                    inverters_data.append(device)
            
            # Get individual inverter data using device/latest endpoint
            individual_inverter_data = {}
            if inverter_sns:
                try:
                    device_data = self.client.get_device_latest(inverter_sns)
<<<<<<< Updated upstream
=======
                    
>>>>>>> Stashed changes
                    # Process the response to get individual generation data
                    # Check for deviceDataList (common in newer API versions) or data -> deviceList
                    items = []
                    if "deviceDataList" in device_data:
                        items = device_data["deviceDataList"]
                    elif "data" in device_data:
                        data = device_data["data"]
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            items = data.get("deviceList", [])
                            
                    for item in items:
                        device_sn = item.get('deviceSn')
                        if device_sn in inverter_sns:
                            individual_inverter_data[device_sn] = item
                except DeyeCloudError as e:
                    logger.warning(f"Failed to get individual inverter data: {e}")
            
            # Store readings for each inverter
            with transaction.atomic():
                for inverter_data in inverters_data:
                    device_sn = inverter_data['deviceSn']
                    individual_data = individual_inverter_data.get(device_sn, {})
                    self._store_inverter_reading(inverter_data, station_data, individual_data)
            
            logger.info(f"Collected data for {len(inverters_data)} inverters")
            
        except DeyeCloudError as e:
            logger.error(f"Failed to collect inverter data: {e}")
            raise
    
    def _store_inverter_reading(self, device_data, station_data, individual_data=None):
        """Store a single inverter reading."""
        # Get or create inverter
        inverter, created = Inverter.objects.get_or_create(
            device_sn=device_data['deviceSn'],
            defaults={
                'device_id': device_data['deviceId'],
                'device_type': device_data['deviceType'],
                'product_id': device_data['productId'],
                'station_id': device_data['stationId'],
            }
        )
        
<<<<<<< Updated upstream
        # Use individual inverter data if available, otherwise fall back to station data
        if individual_data:
            # Extract individual inverter generation data
            # The structure might vary, so we'll try common field names
            generation_power = (
                individual_data.get('generationPower') or 
                individual_data.get('power') or 
                individual_data.get('currentPower') or
                individual_data.get('p') or  # Some APIs use 'p' for power
                0
            )
        else:
            # Fall back to station data (divided among inverters)
=======
        # Extract generation power from individual device data
        generation_power = 0
        battery_soc = None
        
        if individual_data and 'dataList' in individual_data:
            
            # Look for solar generation power in dataList - try multiple fields
            for item in individual_data['dataList']:
                key = item.get('key')
                value = item.get('value', 0)
                
                # Check for SOC while we're iterating
                if key == 'SOC' or key == 'BatterySOC' or key == 'BMSSOC':
                    try:
                        soc_val = float(value)
                        if soc_val > 0:
                            battery_soc = soc_val
                    except (ValueError, TypeError):
                        pass

                # Try different generation power fields
                if key == 'TotalSolarPower':
                    generation_power = float(value)
                    break
                elif key == 'TotalInverterOutputPower':
                    power = float(value)
                    if power > 0:  # Only positive values are generation
                        generation_power = power
                        break
                elif key == 'DCPowerPV1' or key == 'DCPowerPV2':
                    # Sum DC power from PV panels
                    generation_power += float(value)
                elif key == 'InverterOutputPowerL1' or key == 'InverterOutputPowerL2' or key == 'InverterOutputPowerL3':
                    # Sum AC output power from each phase
                    power = float(value)
                    if power > 0:
                        generation_power += power
        else:
            # Fall back to station data
>>>>>>> Stashed changes
            station_generation = station_data.get('generationPower', 0)
            total_inverters = len([d for d in station_data.get('stationList', [{}])[0].get('deviceListItems', []) 
                                  if d.get('deviceType') == 'INVERTER']) if station_data.get('stationList') else 1
            generation_power = station_generation / total_inverters if total_inverters > 0 else 0
        
<<<<<<< Updated upstream
=======
        if battery_soc is None:
            battery_soc = station_data.get('batterySOC')
            
        logger.info(f"Got data for {device_data['deviceSn']}: {generation_power}W, SOC {battery_soc}%")
        
>>>>>>> Stashed changes
        # Store individual inverter data
        reading = InverterReading.objects.create(
            inverter=inverter,
            generation_power=generation_power,
            battery_soc=station_data.get('batterySOC'),  # Station-level battery SOC
            grid_power=station_data.get('gridPower'),
            station_data=station_data,
            connect_status=device_data.get('connectStatus', 1),
            collection_time=timezone.make_aware(datetime.fromtimestamp(device_data.get('collectionTime', 0)))
        )
        
        return reading
    
    def get_latest_readings(self):
        """Get latest reading for each inverter (not just 10 random readings)."""
        from django.db.models import Max
        
        # Get the latest reading for each inverter
        latest_per_inverter = InverterReading.objects.filter(
            inverter__is_active=True
        ).values('inverter__device_sn').annotate(
            latest_timestamp=Max('timestamp')
        )
        
        # Get the actual readings
        readings = []
        for item in latest_per_inverter:
            reading = InverterReading.objects.filter(
                inverter__device_sn=item['inverter__device_sn'],
                timestamp=item['latest_timestamp']
            ).select_related('inverter').first()
            if reading:
                readings.append(reading)
        
        return readings
    
    def get_inverter_history(self, device_sn, hours=24):
        """Get historical data for a specific inverter."""
        since = timezone.now() - timedelta(hours=hours)
        return InverterReading.objects.filter(
            inverter__device_sn=device_sn,
            timestamp__gte=since
        ).order_by('timestamp')
    
    def get_current_generation_summary(self):
        """Get summary of current generation for algorithm."""
        latest_readings = self.get_latest_readings()
        
        # Get the actual station generation from the first reading's station data
        station_generation = 0
        station_battery_soc = 0
        if latest_readings:
            station_data = latest_readings[0].station_data
            station_generation = station_data.get('generationPower', 0)
            station_battery_soc = station_data.get('batterySOC', 0)
        
        avg_battery_soc = sum(r.battery_soc or 0 for r in latest_readings) / len(latest_readings) if latest_readings else 0
        
        return {
            'total_generation_watts': station_generation,  # Use actual station generation
            'average_battery_soc': station_battery_soc,  # Use actual station battery SOC
            'active_inverters': len(latest_readings),
            'timestamp': timezone.now().isoformat(),
            'readings': [
                {
                    'device_sn': r.inverter.device_sn,
                    'generation_power': r.generation_power,  # Individual inverter portion
                    'battery_soc': r.battery_soc,
                    'connect_status': r.connect_status,
                    'timestamp': r.timestamp.isoformat()
                }
                for r in latest_readings
            ]
        }


class EVChargingOptimizer:
    """Service for optimizing EV charging based on solar generation."""
    
    def __init__(self):
        self.inverter_service = InverterDataService()
    
    def get_charging_recommendation(self, vehicle_id, target_soc, current_soc, max_power):
        """
        Get charging recommendation based on current solar generation.
        
        Args:
            vehicle_id: Vehicle identifier
            target_soc: Target battery percentage (0-100)
            current_soc: Current battery percentage (0-100)
            max_power: Maximum charging power in watts
        
        Returns:
            Dictionary with charging recommendation
        """
        # Get current generation data
        generation_data = self.inverter_service.get_current_generation_summary()
        
        # Calculate energy needed
        energy_needed_kwh = (target_soc - current_soc) / 100 * 60  # Assume 60kWh battery
        
        # Available solar power (consider 80% efficiency)
        available_power = generation_data['total_generation_watts'] * 0.8
        
        # Charging recommendation
        if available_power > 1000:  # Minimum threshold for charging
            charging_power = min(available_power, max_power)
            estimated_time_hours = energy_needed_kwh / (charging_power / 1000)
            
            recommendation = {
                'should_charge': True,
                'charging_power_watts': charging_power,
                'estimated_time_hours': estimated_time_hours,
                'energy_source': 'solar',
                'available_solar_watts': generation_data['total_generation_watts'],
                'battery_soc': generation_data['average_battery_soc']
            }
        else:
            recommendation = {
                'should_charge': False,
                'reason': 'Insufficient solar generation',
                'available_solar_watts': generation_data['total_generation_watts'],
                'battery_soc': generation_data['average_battery_soc']
            }
        
        return recommendation
