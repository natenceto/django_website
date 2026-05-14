"""
API Views for EV Charging Platform.
"""
from asgiref.sync import async_to_sync
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta

from renew_website.apps.charging_stations.models import (
    Station, Connector, Transaction, MeterValue, UserRFID
)
from renew_website.apps.charging_stations.registry import station_runtime
from renew_website.apps.charging_stations.services import (
    CommandDispatchError,
    StartChargingCommand,
    StopChargingCommand,
    command_bus,
)

def is_station_active(station_id):
    """Check if station is active."""
    return station_runtime.is_online(station_id)

def get_active_station_count():
    """Get count of active stations."""
    return station_runtime.count_online()
from .serializers import (
    StationListSerializer, StationDetailSerializer, ConnectorSerializer,
    TransactionSerializer, MeterValueSerializer, UserRFIDSerializer,
    ChargingSessionStartSerializer, ChargingSessionStopSerializer,
    StationStatisticsSerializer
)


class StationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and editing stations.
    
    list: Get all stations
    retrieve: Get a specific station
    create: Add a new station (admin only)
    update: Update a station (admin only)
    destroy: Delete a station (admin only)
    """
    queryset = Station.objects.all().prefetch_related('connectors')
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return StationListSerializer
        return StationDetailSerializer
    
    def get_queryset(self):
        queryset = Station.objects.all().prefetch_related('connectors')
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by online/offline
        online = self.request.query_params.get('online')
        if online is not None:
            online_ids = station_runtime.get_all_online()
            if online.lower() == 'true':
                queryset = queryset.filter(id__in=online_ids)
            else:
                queryset = queryset.exclude(id__in=online_ids)
        
        # Filter by connector type
        connector_type = self.request.query_params.get('connector_type')
        if connector_type:
            queryset = queryset.filter(connector_type__icontains=connector_type)
        
        # Filter by min power
        min_power = self.request.query_params.get('min_power')
        if min_power:
            queryset = queryset.filter(power_output__gte=int(min_power))
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def connectors(self, request, pk=None):
        """Get all connectors for a station."""
        station = self.get_object()
        connectors = station.connectors.all()
        serializer = ConnectorSerializer(connectors, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Get recent transactions for a station."""
        station = self.get_object()
        transactions = Transaction.objects.filter(
            connector__station=station
        ).order_by('-started_at')[:50]
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class ConnectorViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing connectors."""
    queryset = Connector.objects.all().select_related('station')
    serializer_class = ConnectorSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = Connector.objects.all().select_related('station')
        
        # Filter by station
        station_id = self.request.query_params.get('station')
        if station_id:
            queryset = queryset.filter(station_id=station_id)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing transactions."""
    queryset = Transaction.objects.all().select_related('connector__station')
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = Transaction.objects.all().select_related('connector__station')
        
        # Filter by station
        station_id = self.request.query_params.get('station')
        if station_id:
            queryset = queryset.filter(connector__station_id=station_id)
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(started_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(started_at__date__lte=end_date)
        
        return queryset.order_by('-started_at')
    
    @action(detail=True, methods=['get'])
    def meter_values(self, request, pk=None):
        """Get meter values for a transaction."""
        transaction = self.get_object()
        meter_values = transaction.meter_values.all().order_by('timestamp')
        serializer = MeterValueSerializer(meter_values, many=True)
        return Response(serializer.data)


class UserRFIDViewSet(viewsets.ModelViewSet):
    """ViewSet for managing RFID tags."""
    queryset = UserRFID.objects.all().prefetch_related('stations')
    serializer_class = UserRFIDSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        queryset = UserRFID.objects.all().prefetch_related('stations')
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        # Search by tag or owner
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(tag__icontains=search) | Q(owner_name__icontains=search)
            )
        
        return queryset


class ChargingSessionView(APIView):
    """API endpoints for starting and stopping charging sessions."""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, action_type):
        """Start or stop a charging session."""
        if action_type == 'start':
            return self._start_session(request)
        elif action_type == 'stop':
            return self._stop_session(request)
        return Response(
            {'error': 'Invalid action. Use "start" or "stop".'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    def _start_session(self, request):
        """Start a new charging session."""
        serializer = ChargingSessionStartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        station_id = serializer.validated_data['station_id']
        connector_id = serializer.validated_data.get('connector_id', 1)
        power_kw = serializer.validated_data.get('power_kw')
        session_context = {
            'vehicle_soc': serializer.validated_data.get('vehicle_soc'),
            'target_soc': serializer.validated_data.get('target_soc', 80.0),
            'estimated_departure_hours': serializer.validated_data.get('estimated_departure_hours'),
            'priority_weight': serializer.validated_data.get('priority_weight'),
            'battery_capacity_kwh': serializer.validated_data.get('battery_capacity_kwh'),
            'max_acceptance_kw': serializer.validated_data.get('max_acceptance_kw'),
            'requested_power_kw': power_kw,
        }
        session_context = {key: value for key, value in session_context.items() if value is not None}
        
        # Check if station is connected
        if not is_station_active(station_id):
            return Response(
                {'error': f'Station {station_id} is not connected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get RFID tag
        rfid_tag = serializer.validated_data.get('rfid_tag')
        if not rfid_tag:
            rfid = UserRFID.objects.filter(is_active=True).first()
            if not rfid:
                return Response(
                    {'error': 'No active RFID tag found'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            rfid_tag = rfid.tag
        
        # TODO: Implement actual RemoteStartTransaction call
        try:
            dispatch_result = command_bus.dispatch(
                StartChargingCommand(
                    station_id=station_id,
                    connector_id=connector_id,
                    id_tag=rfid_tag,
                    requested_power_kw=power_kw,
                    session_context=session_context,
                )
            )
        except CommandDispatchError as exc:
            return Response(
                {'error': f'Failed to send remote start to station {station_id}: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        
        return Response({
            'message': f'Charging session start requested for station {station_id}',
            'station_id': station_id,
            'connector_id': connector_id,
            'rfid_tag': rfid_tag,
            'power_kw': power_kw,
            'command_id': dispatch_result.command_id,
            'session_context': session_context,
        })
    
    def _stop_session(self, request):
        """Stop an active charging session."""
        serializer = ChargingSessionStopSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        transaction_id = serializer.validated_data['transaction_id']
        
        try:
            transaction = Transaction.objects.get(id=transaction_id, status='active')
        except Transaction.DoesNotExist:
            return Response(
                {'error': f'Active transaction {transaction_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        station_id = transaction.connector.station_id
        if not is_station_active(station_id):
            return Response(
                {'error': f'Station {station_id} is not connected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            dispatch_result = command_bus.dispatch(
                StopChargingCommand(
                    station_id=station_id,
                    transaction_id=transaction.id,
                )
            )
        except CommandDispatchError as exc:
            return Response(
                {'error': f'Failed to send remote stop for transaction {transaction_id}: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        
        return Response({
            'message': f'Charging session stop requested for transaction {transaction_id}',
            'transaction_id': transaction_id,
            'station_id': station_id,
            'command_id': dispatch_result.command_id,
        })


class StatisticsView(APIView):
    """API endpoint for charging statistics."""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get overall charging statistics."""
        today = timezone.now().date()
        
        # Station statistics
        total_stations = Station.objects.count()
        online_stations = get_active_station_count()
        
        # Connector statistics
        total_connectors = Connector.objects.count()
        available_connectors = Connector.objects.filter(
            status='available',
            availability='operative'
        ).count()
        
        # Session statistics
        active_sessions = Transaction.objects.filter(status='active').count()
        
        # Energy statistics (today)
        today_transactions = Transaction.objects.filter(
            started_at__date=today
        )
        total_energy_wh = today_transactions.aggregate(
            total=Sum('meter_stop') - Sum('meter_start')
        )['total'] or 0
        total_energy_kwh = round(total_energy_wh / 1000, 2)
        
        total_sessions_today = today_transactions.count()
        
        data = {
            'total_stations': total_stations,
            'online_stations': online_stations,
            'total_connectors': total_connectors,
            'available_connectors': available_connectors,
            'active_sessions': active_sessions,
            'total_energy_kwh': total_energy_kwh,
            'total_sessions_today': total_sessions_today
        }
        
        serializer = StationStatisticsSerializer(data)
        return Response(serializer.data)
