import logging
from django.utils import timezone
from django.contrib.auth.models import User
from .models_alerts import SystemAlert, AlertSubscription, AlertLog
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


class AlertService:
    """Service for managing system alerts and notifications"""
    
    @staticmethod
    def create_alert(title, message, severity='info', category='system', 
                    user=None, station_id=None, transaction_id=None, 
                    source='system', details=None):
        """Create a new system alert and send notifications"""
        try:
            alert = SystemAlert.create_alert(
                title=title,
                message=message,
                severity=severity,
                category=category,
                user=user,
                station_id=station_id,
                transaction_id=transaction_id,
                source=source,
                details=details or {}
            )
            
            # Send notifications to subscribed users
            AlertService._send_notifications(alert)
            
            logger.info(f"Created alert: {alert.title} [{alert.severity}]")
            return alert
            
        except Exception as e:
            logger.error(f"Failed to create alert: {e}")
            return None
    
    @staticmethod
    def _send_notifications(alert):
        """Send notifications to subscribed users"""
        subscriptions = AlertSubscription.objects.filter(
            category=alert.category,
            is_web_enabled=True
        ).select_related('user')
        
        for subscription in subscriptions:
            # Check if severity meets minimum threshold
            if AlertService._should_notify(alert, subscription):
                if subscription.is_email_enabled:
                    AlertService._send_email_notification(alert, subscription.user)
                
                # Log web notification
                AlertLog.objects.create(
                    alert=alert,
                    user=subscription.user,
                    notification_type='web',
                    success=True
                )
    
    @staticmethod
    def _should_notify(alert, subscription):
        """Check if alert severity meets subscription threshold"""
        severity_levels = {'info': 1, 'warning': 2, 'error': 3, 'critical': 4}
        alert_level = severity_levels.get(alert.severity, 1)
        min_level = severity_levels.get(subscription.severity_min, 2)
        return alert_level >= min_level
    
    @staticmethod
    def _send_email_notification(alert, user):
        """Send email notification for alert"""
        try:
            subject = f"[{alert.severity.upper()}] {alert.title}"
            
            message = f"""
Alert Details:
-------------
Title: {alert.title}
Severity: {alert.severity.upper()}
Category: {alert.category}
Time: {alert.created_at.strftime('%Y-%m-%d %H:%M:%S')}

Message:
{alert.message}

Additional Details:
{alert.details}

This is an automated alert from RENEW EV Charging Platform.
"""
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'alerts@renew-energy.com',
                recipient_list=[user.email],
                fail_silently=False
            )
            
            # Log successful email
            AlertLog.objects.create(
                alert=alert,
                user=user,
                notification_type='email',
                success=True
            )
            
        except Exception as e:
            logger.error(f"Failed to send email alert to {user.email}: {e}")
            # Log failed email
            AlertLog.objects.create(
                alert=alert,
                user=user,
                notification_type='email',
                success=False,
                error_message=str(e)
            )
    
    @staticmethod
    def get_alert_statistics():
        """Get alert statistics for dashboard"""
        stats = {
            'total_active': SystemAlert.get_alert_count(),
            'critical': SystemAlert.get_alert_count(severity='critical'),
            'error': SystemAlert.get_alert_count(severity='error'),
            'warning': SystemAlert.get_alert_count(severity='warning'),
            'info': SystemAlert.get_alert_count(severity='info'),
            'by_category': {}
        }
        
        for category, _ in SystemAlert.CATEGORY_CHOICES:
            stats['by_category'][category] = SystemAlert.get_alert_count(category=category)
        
        return stats
    
    @staticmethod
    def acknowledge_alert(alert_id, user):
        """Acknowledge an alert"""
        try:
            alert = SystemAlert.objects.get(id=alert_id)
            alert.acknowledge(user)
            logger.info(f"Alert {alert_id} acknowledged by {user.username}")
            return True
        except SystemAlert.DoesNotExist:
            logger.error(f"Alert {alert_id} not found for acknowledgment")
            return False
    
    @staticmethod
    def resolve_alert(alert_id, user):
        """Resolve an alert"""
        try:
            alert = SystemAlert.objects.get(id=alert_id)
            alert.resolve(user)
            logger.info(f"Alert {alert_id} resolved by {user.username}")
            return True
        except SystemAlert.DoesNotExist:
            logger.error(f"Alert {alert_id} not found for resolution")
            return False


class SystemMonitor:
    """Monitor system events and create alerts automatically"""
    
    @staticmethod
    def log_system_error(title, message, details=None, source='system'):
        """Log a system error alert"""
        return AlertService.create_alert(
            title=title,
            message=message,
            severity='error',
            category='system',
            source=source,
            details=details
        )
    
    @staticmethod
    def log_station_alert(title, message, station_id, severity='warning', details=None):
        """Log a station-related alert"""
        return AlertService.create_alert(
            title=title,
            message=message,
            severity=severity,
            category='station',
            station_id=station_id,
            source='ocpp',
            details=details
        )
    
    @staticmethod
    def log_transaction_alert(title, message, transaction_id, severity='warning', details=None):
        """Log a transaction-related alert"""
        return AlertService.create_alert(
            title=title,
            message=message,
            severity=severity,
            category='transaction',
            transaction_id=transaction_id,
            source='api',
            details=details
        )
    
    @staticmethod
    def log_security_alert(title, message, user=None, details=None):
        """Log a security-related alert"""
        return AlertService.create_alert(
            title=title,
            message=message,
            severity='critical',
            category='security',
            user=user,
            source='middleware',
            details=details
        )
    
    @staticmethod
    def log_performance_alert(title, message, details=None):
        """Log a performance-related alert"""
        return AlertService.create_alert(
            title=title,
            message=message,
            severity='warning',
            category='performance',
            source='monitor',
            details=details
        )


# Convenience functions for easy access
def create_system_alert(title, message, severity='info', **kwargs):
    """Create a system alert"""
    return AlertService.create_alert(title, message, severity, 'system', **kwargs)

def create_station_alert(title, message, station_id, severity='warning', **kwargs):
    """Create a station alert"""
    return AlertService.create_alert(title, message, severity, 'station', station_id=station_id, **kwargs)

def create_security_alert(title, message, user=None, **kwargs):
    """Create a security alert"""
    return AlertService.create_alert(title, message, 'critical', 'security', user=user, **kwargs)
