"""
Power Management and Charging Control Module.

This module handles real-time power management for EV charging stations including:
- Power limiting and load balancing
- Smart charging algorithms
- Energy measurement and billing
- Safety monitoring and protection
"""

import asyncio
import logging
from datetime import datetime, timedelta
from django.utils import timezone
from channels.db import database_sync_to_async
from .models import Station, Connector, Transaction

logger = logging.getLogger('charging_stations')


class PowerManager:
    """Manages power distribution and charging control for EV stations."""
    
    @staticmethod
    def calculate_max_power(station, connector):
        """Calculate maximum power for a station/connector based on configuration."""
        # Default to station's rated power output
        max_power = station.power_output
        
        # Apply safety margin (80% of rated power for continuous operation)
        max_power = max_power * 0.8
        
        return max_power
    
    @staticmethod
    async def set_charging_power(station_id, connector_id, power_kw):
        """Set charging power for a specific connector."""
        try:
            station = await Station.objects.aget(id=station_id)
            connector = await Connector.objects.aget(station=station, connector_id=connector_id)
            
            # Validate power limits
            max_power = PowerManager.calculate_max_power(station, connector)
            if power_kw > max_power:
                logger.warning(f"Requested power {power_kw}kW exceeds max {max_power}kW for {station.address}:{connector_id}")
                power_kw = max_power
            
            # Send OCPP command to set charging power
            from .consumers import ACTIVE_STATIONS
            
            def get_station_consumer(station_id):
                """Get station consumer by ID."""
                return ACTIVE_STATIONS.get(station_id)

            def get_chargepoint(station_id):
                """Get chargepoint by station ID."""
                consumer = ACTIVE_STATIONS.get(station_id)
                if consumer and hasattr(consumer, 'cp'):
                    return consumer.cp
                return None
            
            chargepoint = get_chargepoint(station.serial_number)
            
            if chargepoint:
                # Use OCPP SetChargingProfile command
                charging_profile = {
                    "chargingProfileId": f"power_limit_{connector_id}",
                    "stackLevel": 1,
                    "chargingProfilePurpose": "ChargingStationMaxProfile",
                    "chargingProfileKind": "Absolute",
                    "chargingSchedule": {
                        "chargingRateUnit": "W",
                        "chargingSchedulePeriod": [
                            {
                                "startPeriod": 0,
                                "limit": power_kw * 1000  # Convert kW to W
                            }
                        ]
                    }
                }
                
                # Send the charging profile
                await chargepoint.call_set_charging_profile(
                    connector_id=connector_id,
                    cs_charging_profiles=[charging_profile]
                )
                
                logger.info(f"Set charging power to {power_kw}kW for station {station_id}:{connector_id}")
                return True
            else:
                logger.warning(f"Station {station_id} not connected for power control")
                return False
                
        except Exception as e:
            logger.error(f"Error setting charging power: {e}")
            return False
    
    @staticmethod
    async def stop_charging(station_id, connector_id):
        """Stop charging for a specific connector."""
        try:
            station = await Station.objects.aget(id=station_id)
            
            from .consumers import ACTIVE_STATIONS
            
            def get_station_consumer(station_id):
                """Get station consumer by ID."""
                return ACTIVE_STATIONS.get(station_id)

            def get_chargepoint(station_id):
                """Get chargepoint by station ID."""
                consumer = ACTIVE_STATIONS.get(station_id)
                if consumer and hasattr(consumer, 'cp'):
                    return consumer.cp
                return None
            
            chargepoint = get_chargepoint(station.serial_number)
            
            if chargepoint:
                # Find active transaction for this connector
                transaction = await Transaction.objects.filter(
                    connector__station_id=station_id,
                    connector__connector_id=connector_id,
                    stop_timestamp__isnull=True
                ).afirst()
                
                if transaction:
                    # Send RemoteStopTransaction
                    await chargepoint.call_remote_stop_transaction(transaction.id)
                    logger.info(f"Stopped charging for station {station_id}:{connector_id}")
                    return True
                else:
                    logger.warning(f"No active transaction found for station {station_id}:{connector_id}")
                    return False
            else:
                logger.warning(f"Station {station_id} not connected for charging control")
                return False
                
        except Exception as e:
            logger.error(f"Error stopping charging: {e}")
            return False
    
    @staticmethod
    async def get_station_power_usage(station_id):
        """Get current power usage for a station."""
        try:
            # Get all active transactions for the station
            active_transactions = await Transaction.objects.filter(
                connector__station_id=station_id,
                stop_timestamp__isnull=True
            ).select_related('connector')
            
            total_power = 0
            usage_data = []
            
            for transaction in active_transactions:
                # Get latest meter value for this transaction
                latest_meter = await transaction.meter_values.order_by('-timestamp').afirst()
                if latest_meter:
                    # Calculate power from meter values (simplified)
                    # In real implementation, this would use proper power calculation
                    power_kw = latest_meter.value / 1000  # Convert Wh to kWh for display
                    total_power += power_kw
                    
                    usage_data.append({
                        'connector_id': transaction.connector.connector_id,
                        'power_kw': power_kw,
                        'transaction_id': transaction.id,
                        'start_time': transaction.started_at.isoformat()
                    })
            
            return {
                'station_id': station_id,
                'total_power_kw': total_power,
                'active_connectors': len(active_transactions),
                'usage_data': usage_data
            }
            
        except Exception as e:
            logger.error(f"Error getting station power usage: {e}")
            return None
    
    @staticmethod
    async def check_safety_limits(station_id):
        """Check if station is within safety limits."""
        try:
            station = await Station.objects.aget(id=station_id)
            
            # Get current power usage
            usage = await PowerManager.get_station_power_usage(station_id)
            if not usage:
                return {"safe": True, "reason": "No active charging"}
            
            # Check against station's rated power
            max_power = station.power_output
            current_power = usage['total_power_kw']
            
            # Safety margin: don't exceed 90% of rated power
            safety_limit = max_power * 0.9
            
            if current_power > safety_limit:
                return {
                    "safe": False, 
                    "reason": f"Power usage {current_power}kW exceeds safety limit {safety_limit}kW"
                }
            
            return {"safe": True, "power_usage": current_power, "limit": safety_limit}
            
        except Exception as e:
            logger.error(f"Error checking safety limits: {e}")
            return {"safe": False, "reason": f"Monitoring error: {e}"}
    
    @staticmethod
    async def emergency_stop(station_id, connector_id=None):
        """Emergency stop for a station or specific connector."""
        try:
            station = await Station.objects.aget(id=station_id)
            
            from .consumers import ACTIVE_STATIONS
            
            def get_station_consumer(station_id):
                """Get station consumer by ID."""
                return ACTIVE_STATIONS.get(station_id)

            def get_chargepoint(station_id):
                """Get chargepoint by station ID."""
                consumer = ACTIVE_STATIONS.get(station_id)
                if consumer and hasattr(consumer, 'cp'):
                    return consumer.cp
                return None
            
            chargepoint = get_chargepoint(station.serial_number)
            
            if chargepoint:
                if connector_id:
                    # Stop specific connector
                    await PowerManager.stop_charging(station_id, connector_id)
                else:
                    # Stop all connectors at the station
                    connectors = await Connector.objects.filter(station=station).all()
                    for conn in connectors:
                        await PowerManager.stop_charging(station_id, conn.connector_id)
                
                # Send reset command to station
                await chargepoint.call_reset("Soft")
                logger.warning(f"Emergency stop executed for station {station_id}")
                return True
            else:
                logger.warning(f"Station {station_id} not connected for emergency stop")
                return False
                
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}")
            return False


class SmartCharging:
    """Smart charging algorithms for optimal power distribution."""
    
    @staticmethod
    async def distribute_available_power(station_id, available_power_kw):
        """Distribute available power among active charging sessions."""
        try:
            # Get all active transactions for the station
            active_transactions = await Transaction.objects.filter(
                connector__station_id=station_id,
                stop_timestamp__isnull=True
            ).select_related('connector')
            
            if not active_transactions:
                return {"distributed": False, "reason": "No active charging sessions"}
            
            # Calculate fair distribution
            num_sessions = len(active_transactions)
            power_per_session = available_power_kw / num_sessions
            
            # Apply to each session
            results = []
            for transaction in active_transactions:
                success = await PowerManager.set_charging_power(
                    station_id, 
                    transaction.connector.connector_id, 
                    power_per_session
                )
                results.append({
                    'connector_id': transaction.connector.connector_id,
                    'transaction_id': transaction.id,
                    'power_kw': power_per_session,
                    'success': success
                })
            
            return {
                "distributed": True,
                "available_power_kw": available_power_kw,
                "sessions": num_sessions,
                "power_per_session": power_per_session,
                "results": results
            }
            
        except Exception as e:
            logger.error(f"Error in smart power distribution: {e}")
            return {"distributed": False, "reason": str(e)}
    
    @staticmethod
    async def optimize_charging_schedule(station_id):
        """Optimize charging schedule based on demand and constraints."""
        try:
            station = await Station.objects.aget(id=station_id)
            
            # Get current usage
            usage = await PowerManager.get_station_power_usage(station_id)
            if not usage:
                return {"optimized": False, "reason": "No active charging"}
            
            # Calculate optimal power distribution
            max_power = station.power_output
            current_power = usage['total_power_kw']
            available_power = max_power - current_power
            
            if available_power > 0:
                # Redistribute available power
                result = await SmartCharging.distribute_available_power(station_id, available_power)
                return result
            else:
                return {"optimized": False, "reason": "Station at full capacity"}
                
        except Exception as e:
            logger.error(f"Error in charging optimization: {e}")
            return {"optimized": False, "reason": str(e)}


# Helper functions for external modules
def is_station_connected(station_id):
    """Check if station is connected."""
    from .consumers import ACTIVE_STATIONS
    return station_id in ACTIVE_STATIONS

def get_connected_stations():
    """Get list of all connected station IDs."""
    from .consumers import ACTIVE_STATIONS
    return list(ACTIVE_STATIONS.keys())