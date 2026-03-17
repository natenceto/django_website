from django.urls import path
from . import views

urlpatterns = [
    path('current/', views.current_weather, name='current-weather'),
    path('fetch/', views.fetch_weather, name='fetch-weather'),
]
