"""
URL configuration for DeyeCloud API endpoints.
"""
from django.urls import path
from . import views

app_name = 'deye'

urlpatterns = [
    # Device endpoints
    path('devices/', views.device_list, name='device-list'),
    path('devices/<str:device_sn>/latest/', views.device_latest, name='device-latest'),
    path('devices/<str:device_sn>/measure-points/', views.device_measure_points, name='device-measure-points'),
    path('devices/<str:device_sn>/history/', views.device_history, name='device-history'),
    
    # Station endpoints
    path('stations/', views.station_list, name='station-list'),
    path('stations/with-devices/', views.stations_with_devices, name='stations-with-devices'),
    path('stations/<str:station_id>/latest/', views.station_latest, name='station-latest'),
    path('stations/<str:station_id>/devices/', views.station_devices, name='station-devices'),
    path('stations/<str:station_id>/history/', views.station_history, name='station-history'),
]
