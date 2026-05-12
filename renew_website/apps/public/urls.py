from django.urls import path
from . import views

app_name = "public"
urlpatterns = [
    path("", views.index, name="index"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("map/", views.map, name="map"),
    path("api/recent-transactions/", views.recent_transactions_api, name="recent_transactions_api"),
    path("api/recent-transactions/export/", views.export_recent_transactions_csv, name="recent_transactions_csv"),
    path("api/session-chart-data/", views.session_chart_api, name="session_chart_api"),
]