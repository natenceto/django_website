"""
URL configuration for Deye Hybrid API endpoints (Cloud + Local).
"""
from django.urls import path
from . import views

app_name = 'deye'

urlpatterns = [
    # --- Основни данни за устройства (Хибридни) ---
    # Този път поддържа както специфичен SN, така и Master SN от settings
    path('devices/latest/', views.device_latest, name='device-latest-default'),
    path('devices/<str:device_sn>/latest/', views.device_latest, name='device-latest'),
    
    # --- Управление на режими (EMS) ---
    path('devices/set-mode/', views.set_work_mode, name='device-set-mode'),
    path('devices/get-mode/', views.get_current_work_mode, name='device-get-mode'),
    
    # --- Исторически данни (Само от Cloud) ---
    path('devices/<str:device_sn>/history/', views.device_history, name='device-history'),
    
    # --- Инфраструктура (Станции) ---
    path('stations/', views.station_list, name='station-list'),
    path('stations/<str:station_id>/latest/', views.station_latest, name='station-latest'),
]