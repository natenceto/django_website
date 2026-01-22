"""
URL configuration for energy management API endpoints.
"""
from django.urls import path
from . import views

app_name = 'energy'

urlpatterns = [
    # Dashboard page
    path('', views.energy_dashboard, name='dashboard-page'),
    
    # Inverter monitoring
    path('inverters/status/', views.InverterStatusView.as_view(), name='inverter-status'),
    path('inverters/<str:device_sn>/history/', views.inverter_history, name='inverter-history'),
    
    # EV charging optimization
    path('charging/recommendation/', views.charging_recommendation, name='charging-recommendation'),
    
    # Data management
    path('data/collect/', views.collect_data, name='collect-data'),
    path('dashboard/api/', views.dashboard_data, name='dashboard'),
]
