"""
API v1 URL Configuration.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'stations', views.StationViewSet, basename='station')
router.register(r'connectors', views.ConnectorViewSet, basename='connector')
router.register(r'transactions', views.TransactionViewSet, basename='transaction')
router.register(r'rfid', views.UserRFIDViewSet, basename='rfid')

urlpatterns = [
    path('', include(router.urls)),
    path('sessions/<str:action_type>/', views.ChargingSessionView.as_view(), name='charging-session'),
    path('statistics/', views.StatisticsView.as_view(), name='statistics'),
]
