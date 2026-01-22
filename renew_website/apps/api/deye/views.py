"""
DeyeCloud API Views for Django REST Framework.

Provides endpoints to access DeyeCloud solar/energy data.
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import logging

from .client import DeyeCloudClient, DeyeCloudError

logger = logging.getLogger(__name__)


def get_deye_client():
    """Get a configured DeyeCloud client instance."""
    try:
        return DeyeCloudClient()
    except ValueError as e:
        logger.error(f"DeyeCloud client configuration error: {e}")
        return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_list(request):
    """Get list of all DeyeCloud devices."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
        data = client.get_device_list(page=page, size=size)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_latest(request, device_sn):
    """Get latest data for a device (or multiple devices)."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        data = client.get_device_latest(device_sn)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_measure_points(request, device_sn):
    """Get available measure points for a device."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        data = client.get_device_measure_points(device_sn)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_history(request, device_sn):
    """
    Get historical data from a device.
    
    Query params:
        granularity: 1=daily detail, 2=daily stats, 3=monthly, 4=yearly
        start_at: Start date (format depends on granularity)
        end_at: End date (optional)
        measure_points: Comma-separated measure point names (for granularity=1)
    """
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        granularity = int(request.query_params.get('granularity', 2))
        start_at = request.query_params.get('start_at')
        end_at = request.query_params.get('end_at')
        measure_points_str = request.query_params.get('measure_points')
        
        if not start_at:
            return Response(
                {"error": "start_at is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        measure_points = None
        if measure_points_str:
            measure_points = [mp.strip() for mp in measure_points_str.split(',')]
        
        data = client.get_device_history(
            device_sn, 
            granularity,
            start_at,
            end_at,
            measure_points
        )
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_list(request):
    """Get list of all stations/plants."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
        data = client.get_station_list(page=page, size=size)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stations_with_devices(request):
    """
    Get list of all stations with their devices included.
    
    Query params:
        device_type: Optional filter - INVERTER, MICRO_INVERTER, COLLECTOR, etc.
    """
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
        device_type = request.query_params.get('device_type')
        data = client.get_stations_with_devices(page=page, size=size, device_type=device_type)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_latest(request, station_id):
    """Get latest/real-time data for a station."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        data = client.get_station_latest(station_id)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_devices(request, station_id):
    """Get devices belonging to a station."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
        data = client.get_station_devices(station_id, page=page, size=size)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_history(request, station_id):
    """Get historical data for a station."""
    client = get_deye_client()
    if not client:
        return Response(
            {"error": "DeyeCloud not configured"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    
    try:
        granularity = int(request.query_params.get('granularity', 2))
        start_at = request.query_params.get('start_at')
        end_at = request.query_params.get('end_at')
        
        if not start_at:
            return Response(
                {"error": "start_at is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        data = client.get_station_history(station_id, granularity, start_at, end_at)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)
