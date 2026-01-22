"""
DeyeCloud API Client for Django Integration.

This module provides a wrapper around the DeyeCloud API v1.
API Documentation: https://developer.deyecloud.com/api

Datacenter URLs:
- EU: https://eu1-developer.deyecloud.com/v1.0
- US: https://us1-developer.deyecloud.com/v1.0
"""
import hashlib
import requests
import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Datacenter base URLs
DATACENTER_URLS = {
    'eu': 'https://eu1-developer.deyecloud.com/v1.0'
}


class DeyeCloudClient:
    """
    Client for interacting with DeyeCloud API v1.
    
    Usage:
        client = DeyeCloudClient()
        token = client.get_token()
        devices = client.get_device_list()
    """
    
    TOKEN_CACHE_KEY = "deye_access_token"
    TOKEN_CACHE_TIMEOUT = 7000  # Token valid for ~2 hours, cache for less
    
    def __init__(self, app_id=None, app_secret=None, email=None, password=None, 
                 datacenter=None, company_id=None):
        """
        Initialize the DeyeCloud client.
        
        Args:
            app_id: DeyeCloud App ID (defaults to settings.DEYE_APP_ID)
            app_secret: DeyeCloud App Secret (defaults to settings.DEYE_APP_SECRET)
            email: DeyeCloud account email (defaults to settings.DEYE_EMAIL)
            password: DeyeCloud account password (defaults to settings.DEYE_PASSWORD)
            datacenter: Datacenter region 'eu' or 'us' (defaults to settings.DEYE_DATACENTER or 'eu')
            company_id: Company ID for business accounts (defaults to settings.DEYE_COMPANY_ID or '0')
        """
        self.app_id = app_id or getattr(settings, 'DEYE_APP_ID', None)
        self.app_secret = app_secret or getattr(settings, 'DEYE_APP_SECRET', None)
        self.email = email or getattr(settings, 'DEYE_EMAIL', None)
        self.password = password or getattr(settings, 'DEYE_PASSWORD', None)
        self.datacenter = datacenter or getattr(settings, 'DEYE_DATACENTER', 'eu')
        self.company_id = company_id or getattr(settings, 'DEYE_COMPANY_ID', '0')
        
        if not all([self.app_id, self.app_secret, self.email, self.password]):
            raise ValueError(
                "DeyeCloud credentials not configured. "
                "Set DEYE_APP_ID, DEYE_APP_SECRET, DEYE_EMAIL, DEYE_PASSWORD in settings."
            )
        
        self.base_url = DATACENTER_URLS.get(self.datacenter.lower(), DATACENTER_URLS['eu'])
        self._access_token = None
        self.demo_mode = False
    
    def _hash_password(self, password):
        """Hash password using SHA256 as required by DeyeCloud API."""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def _make_request(self, method, endpoint, data=None, params=None, auth_required=True):
        """
        Make an API request to DeyeCloud.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Request body data
            params: Query parameters
            auth_required: Whether to include access token
            
        Returns:
            API response data (dict)
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
        }
        
        if auth_required:
            token = self.get_token()
            headers["Authorization"] = f"bearer {token}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            
            # Check DeyeCloud API response code
            # Success codes: 0, "0", 1000000, "1000000", or missing
            code = result.get('code')
            success_codes = ['0', '1000000']
            if code is not None and str(code) not in success_codes:
                error_msg = result.get('msg', 'Unknown error')
                logger.error(f"DeyeCloud API error: {error_msg}")
                raise DeyeCloudAPIError(code, error_msg)
            
            return result.get('data', result)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"DeyeCloud request failed: {e}")
            raise DeyeCloudConnectionError(str(e))
    
    def get_token(self, force_refresh=False):
        """
        Get access token, using cached version if available.
        
        Args:
            force_refresh: Force getting a new token
            
        Returns:
            Access token string
        """
        if not force_refresh:
            # Try cache first
            cached_token = cache.get(self.TOKEN_CACHE_KEY)
            if cached_token:
                return cached_token
            
            # Try instance variable
            if self._access_token:
                return self._access_token
        else:
            # Clear cache when forcing refresh
            cache.delete(self.TOKEN_CACHE_KEY)
        
        # Get new token
        token_data = self._obtain_token()
        
        # Handle different response structures
        if isinstance(token_data, dict):
            self._access_token = token_data.get('accessToken') or token_data.get('access_token')
        else:
            raise DeyeCloudAPIError(0, f"Unexpected token response: {token_data}")
        
        if not self._access_token:
            raise DeyeCloudAPIError(0, f"No access token in response: {token_data}")
        
        # Cache the token
        cache.set(self.TOKEN_CACHE_KEY, self._access_token, self.TOKEN_CACHE_TIMEOUT)
        
        return self._access_token
    
    def clear_token_cache(self):
        """Clear cached token to force re-authentication."""
        cache.delete(self.TOKEN_CACHE_KEY)
        self._access_token = None
    
    def _obtain_token(self):
        """
        Obtain a new access token from DeyeCloud API.
        
        Returns:
            Token response data containing accessToken, refreshToken, etc.
        """
        # Token endpoint uses appId as query parameter
        endpoint = f"/account/token?appId={self.app_id}"
        hashed_password = self._hash_password(self.password)
        data = {
            "appSecret": self.app_secret,
            "email": self.email,
            "companyId": self.company_id,
            "password": hashed_password
        }
        
        return self._make_request("POST", endpoint, data=data, auth_required=False)
    
    # =========================================================================
    # Device Management APIs
    # =========================================================================
    
    def get_device_list(self, page=1, size=20):
        """
        Get list of devices associated with the account.
        
        Args:
            page: Page number (default 1)
            size: Page size (default 20)
            
        Returns:
            List of device objects
        """
        endpoint = "/device/list"
        data = {
            "page": page,
            "size": size
        }
        return self._make_request("POST", endpoint, data=data)
    
    def get_device_latest(self, device_sns):
        """
        Get latest data for devices (batch query, up to 10 devices).
        
        Args:
            device_sns: Single device SN (str) or list of device SNs
            
        Returns:
            Latest device data
        """
        endpoint = "/device/latest"
        if isinstance(device_sns, str):
            device_sns = [device_sns]
        data = {"deviceList": device_sns}
        return self._make_request("POST", endpoint, data=data)
    
    def get_device_measure_points(self, device_sn):
        """
        Get available measure points for a device.
        
        Args:
            device_sn: Device serial number
            
        Returns:
            List of available measure points
        """
        endpoint = "/device/measurePoints"
        data = {"deviceSn": device_sn}
        return self._make_request("POST", endpoint, data=data)
    
    def get_device_history(self, device_sn, granularity, start_at, end_at=None, measure_points=None):
        """
        Get historical data from a device.
        
        Args:
            device_sn: Device serial number
            granularity: Data granularity:
                1 = Daily detail (startAt: 'yyyy-MM-dd', measurePoints required)
                2 = Daily stats (startAt/endAt: 'yyyy-MM-dd', up to 31 days)
                3 = Monthly stats (startAt/endAt: 'yyyy-MM', up to 12 months)
                4 = Yearly stats (startAt/endAt: 'yyyy')
            start_at: Start date string (format depends on granularity)
            end_at: End date string (optional for granularity > 1)
            measure_points: List of measure point names (required for granularity=1)
            
        Returns:
            Historical device data
        """
        endpoint = "/device/history"
        data = {
            "deviceSn": device_sn,
            "granularity": granularity,
            "startAt": start_at,
        }
        if end_at:
            data["endAt"] = end_at
        if measure_points:
            data["measurePoints"] = measure_points
        return self._make_request("POST", endpoint, data=data)
    
    # =========================================================================
    # Station/Plant Management APIs
    # =========================================================================
    
    def get_station_list(self, page=1, size=20):
        """
        Get list of stations/plants.
        
        Args:
            page: Page number
            size: Page size
            
        Returns:
            List of station objects
        """
        endpoint = "/station/list"
        data = {
            "page": page,
            "size": size
        }
        return self._make_request("POST", endpoint, data=data)
    
    def get_stations_with_devices(self, page=1, size=20, device_type=None):
        """
        Get list of stations with their devices included.
        This endpoint returns both station and device information.
        
        Args:
            page: Page number
            size: Page size
            device_type: Optional filter - INVERTER, MICRO_INVERTER, COLLECTOR, 
                        BATTERY, MECD, METER, RELAY_BOX, OPTIMIZER, PV_MODULE
            
        Returns:
            List of stations with deviceListItems
        """
        endpoint = "/station/listWithDevice"
        data = {
            "page": page,
            "size": size
        }
        if device_type:
            data["deviceType"] = device_type
        return self._make_request("POST", endpoint, data=data)
    
    def get_station_latest(self, station_id):
        """
        Get latest/real-time data for a station.
        
        Args:
            station_id: Station ID (integer)
            
        Returns:
            Latest station data
        """
        endpoint = "/station/latest"
        data = {"stationId": int(station_id)}
        return self._make_request("POST", endpoint, data=data)
    
    def get_station_devices(self, station_id, page=1, size=20):
        """
        Get devices belonging to a station.
        
        Args:
            station_id: Station ID
            page: Page number
            size: Page size
            
        Returns:
            List of devices in the station
        """
        endpoint = "/station/device"
        data = {
            "stationId": int(station_id),
            "page": page,
            "size": size
        }
        return self._make_request("POST", endpoint, data=data)
    
    def get_station_history(self, station_id, granularity, start_at, end_at=None):
        """
        Get historical data for a station.
        
        Args:
            station_id: Station ID
            granularity: Data granularity (2=daily, 3=monthly, 4=yearly)
            start_at: Start date string
            end_at: End date string
            
        Returns:
            Historical station data
        """
        endpoint = "/station/history"
        data = {
            "stationId": int(station_id),
            "granularity": granularity,
            "startAt": start_at,
        }
        if end_at:
            data["endAt"] = end_at
        return self._make_request("POST", endpoint, data=data)


class DeyeCloudError(Exception):
    """Base exception for DeyeCloud errors."""
    pass


class DeyeCloudAPIError(DeyeCloudError):
    """Exception raised when DeyeCloud API returns an error."""
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"DeyeCloud API Error {code}: {message}")


class DeyeCloudConnectionError(DeyeCloudError):
    """Exception raised when connection to DeyeCloud fails."""
    pass


# Demo data for when DeyeCloud credentials are not configured
DEMO_STATIONS_DATA = {
    "data": {
        "stationList": [
            {
                "id": 61470379,
                "name": "BAS Renew",
                "capacity": 10.0,
                "deviceListItems": [
                    {
                        "deviceSn": "2409109016",
                        "deviceId": "INV001",
                        "deviceType": "INVERTER",
                        "productId": "SOLAR_INVERTER",
                        "connectStatus": 1,
                        "isMaster": True
                    },
                    {
                        "deviceSn": "2409109073",
                        "deviceId": "INV002", 
                        "deviceType": "INVERTER",
                        "productId": "SOLAR_INVERTER",
                        "connectStatus": 1,
                        "isMaster": False
                    }
                ]
            }
        ]
    }
}

DEMO_DEVICE_DATA = {
    "data": [
        {
            "deviceSn": "2409109016",
            "p": 3000,
            "batterySOC": 75.5,
            "gridPower": 1500,
            "dailyEnergy": 25.6,
            "totalEnergy": 1250.8,
            "collectionTime": 1642147200,
            "connectStatus": 1,
            "temperature": 35.2,
            "voltage": 230.0,
            "current": 13.0
        },
        {
            "deviceSn": "2409109073",
            "p": 3000,
            "batterySOC": 75.5,
            "gridPower": 1500,
            "dailyEnergy": 25.6,
            "totalEnergy": 1250.8,
            "collectionTime": 1642147200,
            "connectStatus": 1,
            "temperature": 35.2,
            "voltage": 230.0,
            "current": 13.0
        }
    ]
}

DEMO_STATION_LATEST = {
    "data": {
        "generationPower": 6000,
        "batterySOC": 75.5,
        "gridPower": 1500,
        "dailyEnergy": 51.2,
        "monthlyEnergy": 1536.0,
        "totalEnergy": 25016.0,
        "capacity": 10.0,
        "efficiency": 95.2,
        "collectionTime": 1642147200
    }
}
