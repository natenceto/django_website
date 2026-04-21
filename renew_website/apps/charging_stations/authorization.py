"""
RFID Authorization and Access Control Module.

This module handles:
- RFID tag validation and authorization
- Access control and permissions
- Real-time authorization responses
- Blacklist and whitelist management
"""

import logging
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.cache import cache
from .models import UserRFID, Station, Connector, Transaction

logger = logging.getLogger('charging_stations')


class AuthorizationManager:
    """Manages RFID authorization for charging stations."""
    
    CACHE_TIMEOUT = 300  # 5 minutes cache for authorization results
    
    @staticmethod
    def authorize_tag(tag_id, station_id=None, connector_id=None):
        """
        Authorize an RFID tag for charging.
        
        Args:
            tag_id: RFID tag to authorize
            station_id: Station requesting authorization (optional)
            connector_id: Connector requesting authorization (optional)
            
        Returns:
            dict: Authorization result with status and details
        """
        try:
            # Check cache first for performance
            cache_key = f"auth_{tag_id}_{station_id}_{connector_id}"
            cached_result = cache.get(cache_key)
            if cached_result:
                logger.debug(f"Authorization result from cache: {tag_id}")
                return cached_result
            
            # Get RFID record
            try:
                rfid = UserRFID.objects.get(tag=tag_id, is_active=True)
            except UserRFID.DoesNotExist:
                result = {
                    'status': 'Invalid',
                    'reason': 'RFID tag not found or inactive',
                    'tag_id': tag_id
                }
                cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                return result
            
            # Check if tag is expired
            if rfid.expires_at and rfid.expires_at < timezone.now():
                result = {
                    'status': 'Expired',
                    'reason': 'RFID tag has expired',
                    'tag_id': tag_id,
                    'expired_at': rfid.expires_at.isoformat()
                }
                cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                return result
            
            # Check station access permissions
            if station_id:
                station = Station.objects.filter(id=station_id).first()
                if not station:
                    result = {
                        'status': 'Invalid',
                        'reason': 'Station not found',
                        'tag_id': tag_id,
                        'station_id': station_id
                    }
                    cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                    return result
                
                # Check if RFID has access to this station
                # If RFID has specific stations assigned, check if this station is included
                if rfid.stations.exists():
                    if station not in rfid.stations.all():
                        result = {
                            'status': 'Blocked',
                            'reason': 'RFID tag not authorized for this station',
                            'tag_id': tag_id,
                            'station_id': station_id,
                            'station_name': station.address
                        }
                        cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                        return result
                # If no specific stations assigned, allow access to all stations
                
                # Check if station is operational (allow inactive stations for testing)
                if station.status in ['offline', 'maintenance']:
                    result = {
                        'status': 'Blocked',
                        'reason': f'Station is {station.status}',
                        'tag_id': tag_id,
                        'station_id': station_id,
                        'station_status': station.status
                    }
                    cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                    return result
            
            # Check connector availability
            if connector_id and station_id:
                connector = Connector.objects.filter(
                    station_id=station_id,
                    connector_id=connector_id
                ).first()
                
                if not connector:
                    result = {
                        'status': 'Invalid',
                        'reason': 'Connector not found',
                        'tag_id': tag_id,
                        'connector_id': connector_id
                    }
                    cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                    return result
                
                if connector.status not in ['available', 'preparing']:
                    result = {
                        'status': 'Blocked',
                        'reason': f'Connector is {connector.status}',
                        'tag_id': tag_id,
                        'connector_id': connector_id,
                        'connector_status': connector.status
                    }
                    cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                    return result
                
                if connector.availability != 'operative':
                    result = {
                        'status': 'Blocked',
                        'reason': f'Connector is {connector.availability}',
                        'tag_id': tag_id,
                        'connector_id': connector_id,
                        'connector_availability': connector.availability
                    }
                    cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                    return result
            
            # Check for existing active transaction
            existing_transaction = Transaction.objects.filter(
                id_tag=tag_id,
                stopped_at__isnull=True
            ).first()
            
            if existing_transaction:
                result = {
                    'status': 'ConcurrentTx',
                    'reason': 'User already has an active charging session',
                    'tag_id': tag_id,
                    'existing_transaction_id': str(existing_transaction.transaction_id),
                    'existing_station': existing_transaction.connector.station.address
                }
                cache.set(cache_key, result, AuthorizationManager.CACHE_TIMEOUT)
                return result
            
            # Authorization successful
            result = {
                'status': 'Accepted',
                'reason': 'Authorization successful',
                'tag_id': tag_id,
                'user_info': {
                    'owner_name': rfid.owner_name,
                    'user_id': rfid.user_id if hasattr(rfid, 'user_id') else None,
                    'tag_type': rfid.tag_type if hasattr(rfid, 'tag_type') else 'Unknown'
                },
                'authorization_expiry': (timezone.now() + timedelta(minutes=5)).isoformat()
            }
            
            # Cache successful authorization for shorter time
            cache.set(cache_key, result, 60)  # 1 minute
            
            # Log successful authorization
            logger.info(f"RFID authorization successful: {tag_id} -> {rfid.owner_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error during authorization: {e}")
            return {
                'status': 'InternalError',
                'reason': 'Authorization service error',
                'tag_id': tag_id,
                'error': str(e)
            }
    
    @staticmethod
    def blacklist_tag(tag_id, reason="Manual blacklist"):
        """Add an RFID tag to the blacklist."""
        try:
            rfid = UserRFID.objects.get(tag=tag_id)
            rfid.is_active = False
            rfid.notes = f"BLACKLISTED: {reason} - {timezone.now().isoformat()}"
            rfid.save()
            
            # Clear cache for this tag
            cache.delete_many([f"auth_{tag_id}"])
            
            # Create security alert (log only for now)
            logger.warning(
                f"RFID Tag Blacklisted: {tag_id} ({rfid.owner_name}) - Reason: {reason}"
            )
            
            logger.warning(f"RFID tag blacklisted: {tag_id} - {reason}")
            return True
            
        except UserRFID.DoesNotExist:
            logger.error(f"RFID tag {tag_id} not found for blacklisting")
            return False
        except Exception as e:
            logger.error(f"Error blacklisting RFID tag: {e}")
            return False
    
    @staticmethod
    def get_user_transactions(tag_id, limit=10):
        """Get recent transactions for an RFID tag."""
        try:
            transactions = Transaction.objects.filter(
                id_tag=tag_id
            ).order_by('-start_timestamp')[:limit]
            
            result = []
            for tx in transactions:
                result.append({
                    'transaction_id': str(tx.transaction_id),
                    'station_address': tx.connector.station.address,
                    'connector_id': tx.connector.connector_id,
                    'start_time': tx.start_timestamp.isoformat() if tx.start_timestamp else None,
                    'stop_time': tx.stopped_at.isoformat() if tx.stopped_at else None,
                    'energy_kwh': float(tx.energy_kwh) if tx.energy_kwh else 0.0,
                    'status': 'Active' if not tx.stopped_at else 'Completed'
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting user transactions: {e}")
            return []
    
    @staticmethod
    def validate_tag_format(tag_id):
        """Validate RFID tag format according to ISO 14443."""
        if not tag_id:
            return False, "Empty tag ID"
        
        # Remove whitespace and convert to uppercase
        tag_id = tag_id.strip().upper()
        
        # Check length (typical RFID tags are 4-20 characters)
        if len(tag_id) < 4 or len(tag_id) > 20:
            return False, f"Invalid tag length: {len(tag_id)} characters"
        
        # Check for valid characters (hexadecimal)
        if not all(c in '0123456789ABCDEF' for c in tag_id):
            return False, "Tag contains invalid characters (must be hexadecimal)"
        
        return True, "Valid format"


class AccessControl:
    """Manages access control and permissions for charging stations."""
    
    @staticmethod
    def check_station_access(user_id, station_id):
        """Check if a user has access to a specific station."""
        try:
            # Get user's RFID tags
            user_tags = UserRFID.objects.filter(
                user_id=user_id,
                is_active=True
            )
            
            if not user_tags.exists():
                return False, "User has no active RFID tags"
            
            # Check if any tag has access to the station
            station = Station.objects.get(id=station_id)
            
            for rfid in user_tags:
                if not rfid.stations.exists() or station in rfid.stations.all():
                    return True, f"Access granted via RFID {rfid.tag}"
            
            return False, "No RFID tag has access to this station"
            
        except Station.DoesNotExist:
            return False, "Station not found"
        except Exception as e:
            logger.error(f"Error checking station access: {e}")
            return False, f"Access check error: {e}"
    
    @staticmethod
    def grant_access(tag_id, station_id):
        """Grant station access to an RFID tag."""
        try:
            rfid = UserRFID.objects.get(tag=tag_id, is_active=True)
            station = Station.objects.get(id=station_id)
            
            rfid.stations.add(station)
            
            logger.info(f"Granted station access: {tag_id} -> {station.address}")
            return True
            
        except UserRFID.DoesNotExist:
            logger.error(f"RFID tag {tag_id} not found")
            return False
        except Station.DoesNotExist:
            logger.error(f"Station {station_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error granting access: {e}")
            return False
    
    @staticmethod
    def revoke_access(tag_id, station_id):
        """Revoke station access from an RFID tag."""
        try:
            rfid = UserRFID.objects.get(tag=tag_id)
            station = Station.objects.get(id=station_id)
            
            rfid.stations.remove(station)
            
            logger.info(f"Revoked station access: {tag_id} -> {station.address}")
            return True
            
        except UserRFID.DoesNotExist:
            logger.error(f"RFID tag {tag_id} not found")
            return False
        except Station.DoesNotExist:
            logger.error(f"Station {station_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error revoking access: {e}")
            return False


# Convenience functions for OCPP integration
def authorize_rfid(tag_id, station_id=None, connector_id=None):
    """Authorize RFID tag for OCPP Authorize request."""
    return AuthorizationManager.authorize_tag(tag_id, station_id, connector_id)

def validate_rfid_format(tag_id):
    """Validate RFID tag format."""
    return AuthorizationManager.validate_tag_format(tag_id)
