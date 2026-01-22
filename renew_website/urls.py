"""
URL configuration for renew_website project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("", include("renew_website.apps.public.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("renew_website.apps.accounts.urls")),
    path("charging_stations/", include("renew_website.apps.charging_stations.urls")),
    path("deye/", include("renew_website.apps.api.deye.urls")),
    
    # Account Settings page
    path("account/", TemplateView.as_view(template_name="public/account.html"), name="account"),
    
    # Activity Log page
    path("activity/", TemplateView.as_view(template_name="public/activity.html"), name="activity"),
    
    # API Demo page
    path("api-demo/", TemplateView.as_view(template_name="deye/api_demo.html"), name="api_demo"),
    
    # REST API
    path("api/", include("renew_website.apps.api.urls")),
    
    # JWT Authentication endpoints
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]