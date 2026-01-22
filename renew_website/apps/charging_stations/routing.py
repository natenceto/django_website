# In renew_website/apps/charging_stations/routing.py

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Main OCPP connection pattern for charging stations
    re_path(r'^ws/charging_stations/(?P<station_id>\d+)/?$', consumers.ChargePointConsumer.as_asgi()),
    # Alternative pattern with serial number
    re_path(r'^ws/charging_stations/(?P<station_id>\d+)/(?P<serial_number>[\w-]+)/?$', consumers.ChargePointConsumer.as_asgi()),
    # Browser client connections for status updates
    re_path(r'^ws/stations/status/?$', consumers.StationStatusConsumer.as_asgi()),
]