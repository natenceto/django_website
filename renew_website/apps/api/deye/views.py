"""
Deye API Views за Django REST Framework.
Интегриран с DeyeManager за хибриден достъп (Cloud + Local).
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import logging

from .manager import DeyeManager, DeyeManagerError
from .cloud_client import DeyeCloudError

logger = logging.getLogger(__name__)

def get_manager():
    """Помощна функция за инициализация на мениджъра."""
    try:
        return DeyeManager()
    except Exception as e:
        logger.error(f"Грешка при инициализация на DeyeManager: {e}")
        return None

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_latest(request, device_sn=None):
    """
    Връща последните данни за инвертор.
    Ако е конфигуриран локален достъп, данните идват директно от логера.
    """
    manager = get_manager()
    if not manager:
        return Response({"error": "Deye system not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    
    try:
        # Използваме мениджъра за хибридно извличане
        data = manager.get_latest_data(device_sn)
        return Response(data)
    except DeyeManagerError as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Unexpected error in device_latest: {e}")
        return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_work_mode(request):
    """
    Задава работен режим на инвертора.
    Приема JSON: {"mode": "battery_first"} или {"mode": "zero_export_to_load"}
    """
    manager = get_manager()
    mode = request.data.get('mode')
    
    if not mode:
        return Response({"error": "Mode is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        success = manager.set_work_mode(mode)
        if success:
            return Response({"status": "success", "message": f"Mode changed to {mode}"})
        return Response({"status": "failed", "message": "Inverter rejected the command"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_current_work_mode(request):
    """Връща текущия режим на работа на инвертора."""
    manager = get_manager()
    try:
        data = manager.get_work_mode()
        return Response(data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

# --- Стандартни Облачни Ендпоинти (само за справка/история) ---

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_list(request):
    """Списък с всички фотоволтаични централи в акаунта (Cloud only)."""
    manager = get_manager()
    try:
        page = int(request.query_params.get('page', 1))
        size = int(request.query_params.get('size', 20))
        data = manager.cloud.get_station_list(page=page, size=size)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def device_history(request, device_sn):
    """Исторически данни от облака (графики)."""
    manager = get_manager()
    try:
        granularity = int(request.query_params.get('granularity', 2))
        start_at = request.query_params.get('start_at')
        end_at = request.query_params.get('end_at')
        
        if not start_at:
            return Response({"error": "start_at is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        data = manager.cloud.get_device_history(device_sn, granularity, start_at, end_at)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def station_latest(request, station_id):
    """Общи данни за цялата станция (Cloud only)."""
    manager = get_manager()
    try:
        data = manager.cloud.get_station_latest(station_id)
        return Response(data)
    except DeyeCloudError as e:
        return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)