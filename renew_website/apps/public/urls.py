from django.urls import path
from . import views

app_name = "public"
urlpatterns = [
    path("", views.index, name="index"),
    path("dashboard/live-summary/", views.dashboard_live_summary_api, name="dashboard_live_summary_api"),
    path("dashboard/recent-transactions/", views.recent_transactions_api, name="recent_transactions_api"),
    path("dashboard/recent-transactions.csv", views.recent_transactions_csv, name="recent_transactions_csv"),
    path("dashboard/session-chart/", views.session_chart_api, name="session_chart_api"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("map/", views.map, name="map"),
]