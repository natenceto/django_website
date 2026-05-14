import json

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


def _coerce_alert_limit(raw_limit, default=50, maximum=100):
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, maximum))


def _default_alert_preferences(user):
    defaults = []
    for category, label in SystemAlert.CATEGORY_CHOICES:
        defaults.append({
            'category': category,
            'label': label,
            'severity_min': 'warning',
            'is_web_enabled': True,
            'is_email_enabled': False,
        })
    return defaults


def _ensure_alert_subscriptions(user):
    defaults = _default_alert_preferences(user)
    existing = {
        subscription.category: subscription
        for subscription in AlertSubscription.objects.filter(user=user)
    }

    for default in defaults:
        if default['category'] not in existing:
            AlertSubscription.objects.create(
                user=user,
                category=default['category'],
                severity_min=default['severity_min'],
                is_web_enabled=default['is_web_enabled'],
                is_email_enabled=default['is_email_enabled'],
            )


def _serialize_alert_preferences(user):
    _ensure_alert_subscriptions(user)
    subscriptions = {
        subscription.category: subscription
        for subscription in AlertSubscription.objects.filter(user=user)
    }
    rows = []
    for category, label in SystemAlert.CATEGORY_CHOICES:
        subscription = subscriptions[category]
        rows.append({
            'category': category,
            'label': label,
            'severity_min': subscription.severity_min,
            'is_web_enabled': subscription.is_web_enabled,
            'is_email_enabled': subscription.is_email_enabled,
        })
    return rows


def _serialize_alert(alert):
    return {
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
        'details': alert.details,
    }


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"


class AccountSettingsView(LoginRequiredMixin, TemplateView):
    template_name = "public/account.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['account_settings'] = {
            'firstName': self.request.user.first_name or '',
            'lastName': self.request.user.last_name or '',
            'email': self.request.user.email or '',
            'phone': '',
            'company': '',
            'role': 'admin' if self.request.user.is_staff else 'viewer',
            'language': 'en',
            'timezone': 'Europe/Sofia',
            'dateFormat': 'YYYY-MM-DD',
            'theme': 'light',
            'webhookUrl': '',
            'transactionWebhook': '',
        }
        context['alert_severities'] = list(SystemAlert.SEVERITY_CHOICES)
        context['initial_alert_preferences'] = _serialize_alert_preferences(self.request.user)
        return context


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
        limit = _coerce_alert_limit(request.GET.get('limit', 50))
        
        alerts = SystemAlert.get_active_alerts(severity, category)[:limit]
        alert_data = [_serialize_alert(alert) for alert in alerts]
        
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


class AlertPreferencesView(LoginRequiredMixin, View):
    """API for managing per-category alert delivery preferences."""

    def get(self, request: HttpRequest) -> JsonResponse:
        return JsonResponse({
            'preferences': _serialize_alert_preferences(request.user),
            'severity_choices': [
                {'value': value, 'label': label}
                for value, label in SystemAlert.SEVERITY_CHOICES
            ],
        })

    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON payload'}, status=400)

        preferences = payload.get('preferences')
        if not isinstance(preferences, list):
            return JsonResponse({'error': 'Preferences payload must be a list'}, status=400)

        allowed_categories = {value for value, _ in SystemAlert.CATEGORY_CHOICES}
        allowed_severities = {value for value, _ in SystemAlert.SEVERITY_CHOICES}

        _ensure_alert_subscriptions(request.user)
        subscriptions = {
            subscription.category: subscription
            for subscription in AlertSubscription.objects.filter(user=request.user)
        }

        for item in preferences:
            category = item.get('category')
            severity_min = item.get('severity_min', 'warning')
            if category not in allowed_categories:
                return JsonResponse({'error': f'Unsupported alert category: {category}'}, status=400)
            if severity_min not in allowed_severities:
                return JsonResponse({'error': f'Unsupported severity: {severity_min}'}, status=400)

            subscription = subscriptions[category]
            subscription.severity_min = severity_min
            subscription.is_web_enabled = bool(item.get('is_web_enabled', False))
            subscription.is_email_enabled = bool(item.get('is_email_enabled', False))
            subscription.save(update_fields=['severity_min', 'is_web_enabled', 'is_email_enabled'])

        return JsonResponse({
            'message': 'Alert preferences updated successfully',
            'preferences': _serialize_alert_preferences(request.user),
        })