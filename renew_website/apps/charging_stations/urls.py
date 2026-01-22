from django.urls import path
from django.contrib.auth.decorators import login_required, user_passes_test
from . import views

app_name = "charging_stations"

admin_required = user_passes_test(lambda u: u.is_staff)

urlpatterns = [
    path("stations/", login_required(admin_required(views.stations)), name="stations"),
    path("statistics/", login_required(admin_required(views.statistics)), name="statistics"),
    path("tables/", login_required(admin_required(views.tables)), name="tables"),
]