"""
Admin URLs for professional management interface.
"""
from django.urls import path
from . import views

app_name = 'portal'

urlpatterns = [
    # Admin Dashboard
    path('dashboard/', views.admin_dashboard, name='dashboard'),
    
    # Data Management
    path('data-management/', views.data_management, name='data_management'),
    
    # System Settings
    path('system-settings/', views.system_settings, name='system_settings'),
]
