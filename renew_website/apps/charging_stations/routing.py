# renew_website/apps/charging_stations/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # OCPP endpoint (stations) - accept with and without trailing slash
    re_path(r"^ws/charging_stations/(?P<station_id>\d+)/?$", consumers.ChargePointConsumer.as_asgi()),
    re_path(r"^ws/charging_stations/(?P<station_id>\d+)/(?P<ocpp_identity>[^/]+)/?$", consumers.ChargePointConsumer.as_asgi()),

    # Browser dashboard endpoint (status + SoC)
    re_path(r"^ws/stations/status/?$", consumers.StationStatusConsumer.as_asgi()),
    re_path(r"^ws/station/(?P<station_id>\d+)/?$", consumers.StationStatusConsumer.as_asgi()),
]