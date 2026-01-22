"""
API URL Configuration.

Supports API versioning through URL paths:
- /api/v1/ - Version 1 (current)
"""
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView
)

app_name = 'api'

urlpatterns = [
    # API v1
    path('v1/', include('renew_website.apps.api.v1.urls')),
    
    # DeyeCloud Integration
    path('deye/', include('renew_website.apps.api.deye.urls')),
    
    # Energy Management & EV Charging
    path('energy/', include('renew_website.apps.api.energy.urls')),
    
    # API Documentation (OpenAPI/Swagger)
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
]
