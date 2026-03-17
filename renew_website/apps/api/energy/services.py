"""
Energy data collection and management services.
"""
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction

from renew_website.apps.api.deye.cloud_client import DeyeCloudClient, DeyeCloudError
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
            station_data = self.client.station_latest(self.station_id)
            
            # Get station with devices to find inverters
            # Refactored: get_station_list returns list of stations directly now
            stations_list = self.client.get_station_list(page=1, size=20)
            
            # Find our station
            station = None
            for s in stations_list:
                if str(s.get('id')) == str(self.station_id):
                    station = s
                    break
            
            if not station:
                logger.error(f"Station {self.station_id} not found in account")
                return
            
            # Get inverter device SNs
            inverter_sns = []
            
            # Extract devices from the station object returned by get_station_list
            devices = station.get('deviceListItems') or []
            for device in devices:
                if device.get('deviceType') == 'INVERTER':
                    inverter_sns.append(device.get('deviceSn'))
                    # inverters_data.append(device) # Fetching latest data below
            
            # Get individual inverter data using device/latest endpoint
            individual_inverter_data = {}
            if inverter_sns:
                try:
                    # Pass list of SNs
                    device_data = self.client.get_device_latest(inverter_sns)
                    
                    # Refactored data extraction based on actual Deye Cloud structure
                    items = []
                    # 1. Direct deviceDataList
                    if isinstance(device_data, dict):
                        if "deviceDataList" in device_data:
                            items = device_data["deviceDataList"]
                        # 2. Wrapped data -> deviceList or deviceDataList
                        elif "data" in device_data:
                            data_part = device_data["data"]
                            if isinstance(data_part, list):
                                items = data_part
                            elif isinstance(data_part, dict):
                                items = data_part.get("deviceList") or data_part.get("deviceDataList") or []
                        # 3. Direct deviceList
                        elif "deviceList" in device_data:
                            items = device_data["deviceList"]

                    for item in items:
                        if not item: continue
                        device_sn = item.get('deviceSn')
                        if device_sn:
                            individual_inverter_data[device_sn] = item
                            
                except Exception as e:
                    logger.warning(f"Failed to get individual inverter data: {e}")
            
            # Store readings for each inverter
            with transaction.atomic():
                for device_sn in inverter_sns:
                    # Find device info in initial station list
                    inverter_device_info = {}
                    for d in devices:
                         if d.get('deviceSn') == device_sn:
                             inverter_device_info = d
                             break
                    
                    if not inverter_device_info: continue

                    individual_data = individual_inverter_data.get(device_sn, {})
                    self._store_inverter_reading(inverter_device_info, station_data, individual_data)
            
            logger.info(f"Collected data for {len(inverter_sns)} inverters")
            
        except DeyeCloudError as e:
            logger.error(f"Failed to collect inverter data: {e}")
            raise
    
    def _store_inverter_reading(self, device_data, station_data, individual_data=None):
        """Store a single inverter reading."""
        # Get or create inverter
        inverter, created = Inverter.objects.get_or_create(
            device_sn=device_data['deviceSn'],
            defaults={
                'device_id': str(device_data.get('deviceId', '')),
                'device_type': device_data.get('deviceType', 'INVERTER'),
                'product_id': device_data.get('productId', ''),
                # Cannot set station_id directly as it's a FK to local Station model
                # 'station_id': str(device_data.get('stationId', self.station_id)),
            }
        )
        
        # Extract generation power from individual device data
        generation_power = 0.0
        battery_soc = 0.0
        grid_power = 0.0

        if individual_data:
            # Try to grab metrics from dataList if present
            data_list = individual_data.get('dataList', [])
            for item in data_list:
                key = item.get('key')
                # Deye API returns string values sometimes
                try:
                    val = float(item.get('value', 0) or 0)
                except (ValueError, TypeError):
                    val = 0.0
                
                if key in ['TotalSolarPower', 'ActivePower', 'Pac', 'GenerationPower']:
                     generation_power = val
                
                if key in ['BatterySOC', 'SOC', 'BMSSOC']:
                     battery_soc = val
                
                if key in ['GridActivePower', 'TotalGridPower', 'GridPower']:
                     grid_power = val
            
            # If standard keys exist at root (override dataList if present and valid)
            if individual_data.get('generationPower'): generation_power = float(individual_data['generationPower'])
            if individual_data.get('batterySOC'): battery_soc = float(individual_data['batterySOC'])
            if individual_data.get('gridPower'): grid_power = float(individual_data['gridPower'])

        # Create Reading
        InverterReading.objects.create(
            inverter=inverter,
            generation_power=generation_power,
            battery_soc=battery_soc,
            grid_power=grid_power,
            connect_status=device_data.get('connectStatus', 0),
            station_data=individual_data,
            timestamp=timezone.now(),
            collection_time=timezone.now()
        )
        

        if battery_soc is None:
            battery_soc = station_data.get('batterySOC')
            
        logger.info(f"Got data for {device_data['deviceSn']}: {generation_power}W, SOC {battery_soc}%")
        
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
