"""
Weather service for fetching and storing meteorological data.
Uses Open-Meteo API (free, no key required) which provides solar irradiance data vital for PV forecasting.
"""
import requests
import logging
from django.conf import settings
from django.utils import timezone
from .models import WeatherLog

logger = logging.getLogger(__name__)

# Default location (Block 25A, BAS IV km., g.k. Geo Milev 25A, 1113 Sofia)
DEFAULT_LAT = 42.67644483679445
DEFAULT_LON = 23.36893689356358

class WeatherService:
    def __init__(self):
        self.lat = getattr(settings, 'LOCATION_LAT', DEFAULT_LAT)
        self.lon = getattr(settings, 'LOCATION_LON', DEFAULT_LON)
        # Open-Meteo URL
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def fetch_current_weather(self):
        """
        Fetches current weather data including solar irradiance.
        """
        try:
            params = {
                "latitude": self.lat,
                "longitude": self.lon,
                "current": [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "cloud_cover",
                    "wind_speed_10m",
                    "surface_pressure",
                    "precipitation",
                    "shortwave_radiation", # GHI in W/m²
                    "is_day"
                ],
                "timezone": "auto"
            }
            
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            current = data.get("current", {})
            
            if not current:
                logger.warning("No current weather data in response")
                return None

            return {
                "temp_c": current.get("temperature_2m"),
                "humidity": current.get("relative_humidity_2m"),
                "cloud_cover": current.get("cloud_cover"),
                "wind_kph": current.get("wind_speed_10m"),
                "pressure_hpa": current.get("surface_pressure"),
                "precipitation_mm": current.get("precipitation"),
                "irradiance_wm2": current.get("shortwave_radiation"),
                "is_day": current.get("is_day") == 1,
                "timestamp": current.get("time"), # ISO string
                "raw": data
            }

        except Exception as e:
            logger.error(f"Failed to fetch weather from Open-Meteo: {e}")
            return None

    def store_weather_log(self):
        """
        Fetches data and stores it in the database.
        """
        data = self.fetch_current_weather()
        if not data:
            return None

        try:
            # Timestamp from API is usually ISO without timezone or UTC
            # We trust Django auto_now or the API time if precise
            # For simplicity, we use timezone.now() for record creation time
            
            log = WeatherLog.objects.create(
                temp_c=data["temp_c"],
                humidity=data.get("humidity", 0),
                cloud_cover=data.get("cloud_cover", 0),
                wind_kph=data.get("wind_kph", 0),
                pressure_hpa=data.get("pressure_hpa"),
                precipitation_mm=data.get("precipitation_mm", 0),
                irradiance_wm2=data.get("irradiance_wm2", 0),
                source="open-meteo",
                raw_data=data.get("raw", {})
            )
            logger.info(f"Stored weather log: {log}")
            return log
        except Exception as e:
            logger.error(f"Failed to save weather log: {e}")
            return None
