from django.views.generic.base import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.views import View
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.sessions.models import Session
from .models import UserSession
from .models_alerts import SystemAlert, AlertSubscription
from .services import AlertService


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"


class LogoutView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        logout(request)
        return redirect('public:index')
    
    def post(self, request: HttpRequest) -> HttpResponse:
        logout(request)
        return redirect('public:index')


@method_decorator(csrf_exempt, name='dispatch')
class SessionManagementView(LoginRequiredMixin, View):
    """API for managing user sessions"""
    
    def get(self, request: HttpRequest) -> JsonResponse:
        """Get all active sessions for the user"""
        sessions = UserSession.get_active_sessions(request.user)
        current_session_key = request.session.session_key
        
        session_data = []
        for session in sessions:
            session_data.append({
                'id': session.id,
                'session_key': session.session_key,
                'device_info': session.device_info,
                'ip_address': session.ip_address,
                'location': session.location,
                'created_at': session.created_at.isoformat(),
                'last_activity': session.last_activity.isoformat(),
                'is_current': session.session_key == current_session_key,
                'is_active': session.is_active
            })
        
        return JsonResponse({
            'sessions': session_data,
            'total_count': len(session_data),
            'current_session': current_session_key
        })
    
    def post(self, request: HttpRequest) -> JsonResponse:
        """Terminate a specific session"""
        import json
        data = json.loads(request.body)
        session_key = data.get('session_key')
        
        if not session_key:
            return JsonResponse({'error': 'Session key required'}, status=400)
        
        # Don't allow terminating current session
        if session_key == request.session.session_key:
            return JsonResponse({'error': 'Cannot terminate current session'}, status=400)
        
        success = UserSession.terminate_session(session_key)
        
        if success:
            return JsonResponse({'message': 'Session terminated successfully'})
        else:
            return JsonResponse({'error': 'Session not found'}, status=404)
    
    def delete(self, request: HttpRequest) -> JsonResponse:
        """Terminate all sessions except current"""
        current_session_key = request.session.session_key
        sessions = UserSession.get_active_sessions(request.user)
        
        terminated_count = 0
        for session in sessions:
            if session.session_key != current_session_key:
                UserSession.terminate_session(session.session_key)
                terminated_count += 1
        
        return JsonResponse({
            'message': f'Terminated {terminated_count} sessions',
            'terminated_count': terminated_count
        })


@method_decorator(csrf_exempt, name='dispatch')
class AlertsView(LoginRequiredMixin, View):
    """API for managing system alerts"""
    
    def get(self, request: HttpRequest) -> JsonResponse:
        """Get alerts with optional filters"""
        severity = request.GET.get('severity')
        category = request.GET.get('category')
        limit = int(request.GET.get('limit', 50))
        
        alerts = SystemAlert.get_active_alerts(severity, category)[:limit]
        
        alert_data = []
        for alert in alerts:
            alert_data.append({
                'id': alert.id,
                'title': alert.title,
                'message': alert.message,
                'severity': alert.severity,
                'category': alert.category,
                'created_at': alert.created_at.isoformat(),
                'is_acknowledged': alert.is_acknowledged,
                'is_resolved': alert.is_resolved,
                'station_id': alert.station_id,
                'transaction_id': str(alert.transaction_id) if alert.transaction_id else None,
                'source': alert.source,
                'details': alert.details
            })
        
        # Get statistics
        stats = AlertService.get_alert_statistics()
        
        return JsonResponse({
            'alerts': alert_data,
            'statistics': stats,
            'total_count': len(alert_data)
        })
    
    def post(self, request: HttpRequest) -> JsonResponse:
        """Create a new alert (admin only)"""
        if not request.user.is_staff:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        import json
        data = json.loads(request.body)
        
        alert = AlertService.create_alert(
            title=data.get('title'),
            message=data.get('message'),
            severity=data.get('severity', 'info'),
            category=data.get('category', 'system'),
            source='manual',
            details=data.get('details', {})
        )
        
        if alert:
            return JsonResponse({
                'message': 'Alert created successfully',
                'alert_id': alert.id
            })
        else:
            return JsonResponse({'error': 'Failed to create alert'}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class AlertActionView(LoginRequiredMixin, View):
    """API for alert actions (acknowledge, resolve)"""
    
    def post(self, request: HttpRequest, alert_id: int) -> JsonResponse:
        """Perform action on alert"""
        import json
        data = json.loads(request.body)
        action = data.get('action')
        
        if action == 'acknowledge':
            success = AlertService.acknowledge_alert(alert_id, request.user)
            if success:
                return JsonResponse({'message': 'Alert acknowledged'})
            else:
                return JsonResponse({'error': 'Alert not found'}, status=404)
        
        elif action == 'resolve':
            success = AlertService.resolve_alert(alert_id, request.user)
            if success:
                return JsonResponse({'message': 'Alert resolved'})
            else:
                return JsonResponse({'error': 'Alert not found'}, status=404)
        
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)