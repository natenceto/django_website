from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
import logging

from .services import WeatherService
from .models import WeatherLog
from .serializers import WeatherLogSerializer
from renew_website.apps.api.schema import OpenApiResponse, OpenApiTypes, extend_schema

logger = logging.getLogger(__name__)

@extend_schema(responses={200: WeatherLogSerializer, 503: OpenApiResponse(response=OpenApiTypes.OBJECT)})
@api_view(['GET'])
# @permission_classes([IsAuthenticated]) # Optional: public weather endpoint?
def current_weather(request):
    """
    Get current weather logs (from DB cache or fetched live).
    """
    # Try to get very recent log (< 15 mins)
    recent = WeatherLog.objects.filter(
        timestamp__gte=timezone.now() - timezone.timedelta(minutes=15)
    ).first()

    if recent:
        serializer = WeatherLogSerializer(recent)
        return Response(serializer.data)

    # Else fetch new
    service = WeatherService()
    log = service.store_weather_log()
    
    if log:
        serializer = WeatherLogSerializer(log)
        return Response(serializer.data)
    
    return Response({"error": "Failed to fetch weather data"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

@extend_schema(request=None, responses={200: WeatherLogSerializer, 503: OpenApiResponse(response=OpenApiTypes.OBJECT)})
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def fetch_weather(request):
    """Force fetch weather data."""
    service = WeatherService()
    log = service.store_weather_log()
    
    if log:
        serializer = WeatherLogSerializer(log)
        return Response(serializer.data)
    
    return Response({"error": "Failed to fetch weather data"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
