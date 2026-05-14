from django.urls import path

from renew_website.apps.api.schema import extend_schema

from . import views


urlpatterns = [
    path('devices/latest/', extend_schema(exclude=True)(views.device_latest_default), name='device-latest-default'),
    path('devices/<str:device_sn>/latest/', extend_schema(exclude=True)(views.device_latest), name='device-latest'),
    path('devices/set-mode/', extend_schema(exclude=True)(views.set_work_mode), name='device-set-mode'),
    path('devices/get-mode/', extend_schema(exclude=True)(views.get_current_work_mode), name='device-get-mode'),
    path('devices/<str:device_sn>/history/', extend_schema(exclude=True)(views.device_history), name='device-history'),
    path('stations/', extend_schema(exclude=True)(views.station_list), name='station-list'),
    path('stations/<str:station_id>/latest/', extend_schema(exclude=True)(views.station_latest), name='station-latest'),
]