"""
Energy management API views for EV charging optimization.
"""
import logging
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from django.shortcuts import render
from django.utils import timezone
from rest_framework.views import APIView

from .services import InverterDataService, EVChargingOptimizer
from .models import InverterReading
from .serializers import (
    InverterReadingSerializer, 
    DashboardDataSerializer,
    ChargingRecommendationRequestSerializer,
    ChargingRecommendationResponseSerializer
)

logger = logging.getLogger(__name__)


class InverterStatusView(APIView):
    """Get current status of all inverters."""
    permission_classes = [IsAuthenticated]
    serializer_class = InverterReadingSerializer
    
    def get(self, request):
        try:
            service = InverterDataService()
            data = service.get_current_generation_summary()
            serializer = DashboardDataSerializer(data=data)
            if serializer.is_valid():
                return Response(serializer.data)
            return Response(data)
        except Exception as e:
            logger.error(f"Failed to get inverter status: {e}")
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inverter_history(request, device_sn):
    """Get historical data for a specific inverter."""
    try:
        hours = int(request.query_params.get('hours', 24))
        service = InverterDataService()
        
        readings = service.get_inverter_history(device_sn, hours)
        
        data = {
            'device_sn': device_sn,
            'period_hours': hours,
            'readings': [
                {
                    'timestamp': r.timestamp.isoformat(),
                    'generation_power': r.generation_power,
                    'battery_soc': r.battery_soc,
                    'grid_power': r.grid_power,
                    'connect_status': r.connect_status
                }
                for r in readings
            ]
        }
        
        return Response(data)
    except Exception as e:
        logger.error(f"Failed to get inverter history: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    """
    Get EV charging recommendation based on current conditions.
    
    Request body:
    {
        "vehicle_id": "vehicle_001",
        "target_soc": 80,
        "current_soc": 30,
        "max_power": 7200
    }
    """
    try:
        vehicle_id = request.data.get('vehicle_id')
        target_soc = int(request.data.get('target_soc'))
        current_soc = int(request.data.get('current_soc'))
        max_power = float(request.data.get('max_power'))
        
        if not all([vehicle_id, target_soc, current_soc, max_power]):
            return Response(
                {"error": "Missing required fields: vehicle_id, target_soc, current_soc, max_power"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        optimizer = EVChargingOptimizer()
        recommendation = optimizer.get_charging_recommendation(
            vehicle_id, target_soc, current_soc, max_power
        )
        
        return Response(recommendation)
        
    except (ValueError, TypeError) as e:
        return Response(
            {"error": f"Invalid data format: {e}"},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        logger.error(f"Failed to get charging recommendation: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collect_data(request):
    """Manually trigger data collection from inverters."""
    try:
        service = InverterDataService()
        service.collect_current_data()
        
        return Response({
            "message": "Data collection completed",
            "timestamp": timezone.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to collect data: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_data(request):
    """Get comprehensive dashboard data for monitoring."""
    try:
        service = InverterDataService()
        
        # Current generation summary
        current_data = service.get_current_generation_summary()
        
        # Recent readings
        recent_readings = service.get_latest_readings()
        
        # Calculate daily stats - use station data to avoid double counting
        today = timezone.now().date()
        
        # Get all readings for today to calculate energy and peak
        today_readings = InverterReading.objects.filter(
            timestamp__date=today
        ).order_by('timestamp')
        
        # Calculate total energy today properly
        total_energy_today = 0
        if len(today_readings) > 1:
            for i in range(1, len(today_readings)):
                prev_power = today_readings[i-1].station_data.get('generationPower', 0) if today_readings[i-1].station_data else 0
                curr_power = today_readings[i].station_data.get('generationPower', 0) if today_readings[i].station_data else 0
                avg_power = (prev_power + curr_power) / 2
                time_diff = (today_readings[i].timestamp - today_readings[i-1].timestamp).total_seconds() / 3600  # hours
                total_energy_today += (avg_power / 1000) * time_diff  # kWh
        
        dashboard = {
            'current': current_data,
            'daily_stats': {
                'total_energy_kwh': round(total_energy_today, 2),
                'peak_generation_watts': max(
                    (r.station_data.get('generationPower', 0) if r.station_data else 0) for r in today_readings
                ) if today_readings else 0,
                'average_battery_soc': sum(
                    r.battery_soc or 0 for r in recent_readings
                ) / len(recent_readings) if recent_readings else 0
            },
            'recent_readings': [
                {
                    'device_sn': r.inverter.device_sn,
                    'generation_power': r.generation_power,
                    'battery_soc': r.battery_soc,
                    'timestamp': r.timestamp.isoformat()
                }
                for r in recent_readings[:5]
            ]
        }
        
        return Response(dashboard)
        
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        return Response(
            {"error": str(e)}, 
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )


def energy_dashboard(request):
    """Energy management dashboard page."""
    return render(request, 'deye/dashboard.html')
