from django.urls import path
from django.contrib.auth.decorators import login_required, user_passes_test
from . import views

app_name = "charging_stations"

admin_required = user_passes_test(lambda u: u.is_staff)

urlpatterns = [
    path("stations/", login_required(admin_required(views.stations)), name="stations"),
    path("statistics/", login_required(admin_required(views.statistics)), name="statistics"),
    path("statistics/export/<str:export_kind>/", login_required(admin_required(views.statistics_export)), name="statistics_export"),
    path("tables/", login_required(admin_required(views.tables)), name="tables"),

    # SoC API endpoints
    path('api/station/<int:station_id>/soc/current/', login_required(views.get_current_soc), name='get_current_soc'),
    path('api/station/<int:station_id>/soc/history/', login_required(views.get_soc_history), name='get_soc_history'),
    path('api/station/<int:station_id>/soc/config/', login_required(views.update_station_soc_config), name='update_station_soc_config'),
]
