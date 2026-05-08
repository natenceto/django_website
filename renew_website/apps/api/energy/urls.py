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
    
    # Energy Recommendations (NEW)
    path('recommendations/', views.energy_recommendations, name='energy-recommendations'),
    path('recommendations/direct-apply/', views.direct_apply_inverter_mode, name='direct-apply-inverter-mode'),
    path('recommendations/<int:recommendation_id>/apply/', views.apply_energy_recommendation, name='apply-energy-recommendation'),
    path('recommendations/<int:recommendation_id>/ignore/', views.ignore_energy_recommendation, name='ignore-energy-recommendation'),
    path('recommendations/history/', views.energy_recommendations_history, name='energy-recommendations-history'),
    
    # Data management
    path('data/collect/', views.collect_data, name='collect-data'),
    path('dashboard/api/', views.dashboard_data, name='dashboard'),
    path('export/inverter-data/', views.export_inverter_data_csv, name='export-inverter-data'),
    
    # Real-time charts
    path('chart-data/', views.chart_data, name='chart-data'),
    path('chart-data/export/', views.export_chart_csv, name='chart-data-export'),
]
