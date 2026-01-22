from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
import json


class SystemAlert(models.Model):
    """System-wide alerts for important events and errors"""
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]
    
    CATEGORY_CHOICES = [
        ('system', 'System'),
        ('station', 'Station'),
        ('transaction', 'Transaction'),
        ('security', 'Security'),
        ('performance', 'Performance'),
        ('maintenance', 'Maintenance'),
    ]
    
    title = models.CharField(max_length=200)
    message = models.TextField()
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='info')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system')
    
    # Optional fields
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                           help_text="User associated with this alert")
    station_id = models.CharField(max_length=50, null=True, blank=True)
    transaction_id = models.UUIDField(null=True, blank=True)
    
    # Metadata
    source = models.CharField(max_length=100, help_text="Source of the alert (e.g., 'middleware', 'ocpp', 'api')")
    details = models.JSONField(default=dict, blank=True, help_text="Additional alert data")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='acknowledged_alerts')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='resolved_alerts')
    
    # Status
    is_active = models.BooleanField(default=True)
    is_acknowledged = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['severity', 'is_active']),
            models.Index(fields=['category', 'created_at']),
            models.Index(fields=['user', 'created_at']),
        ]
    
    def __str__(self):
        return f"[{self.severity.upper()}] {self.title}"
    
    def acknowledge(self, user):
        """Acknowledge the alert"""
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        self.acknowledged_by = user
        self.save()
    
    def resolve(self, user):
        """Resolve the alert"""
        self.is_resolved = True
        self.is_active = False
        self.resolved_at = timezone.now()
        self.resolved_by = user
        self.save()
    
    @classmethod
    def create_alert(cls, title, message, severity='info', category='system', 
                    user=None, station_id=None, transaction_id=None, 
                    source='system', details=None):
        """Create a new system alert"""
        return cls.objects.create(
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
    
    @classmethod
    def get_active_alerts(cls, severity=None, category=None):
        """Get active alerts with optional filters"""
        queryset = cls.objects.filter(is_active=True)
        
        if severity:
            queryset = queryset.filter(severity=severity)
        if category:
            queryset = queryset.filter(category=category)
            
        return queryset
    
    @classmethod
    def get_alert_count(cls, severity=None, category=None):
        """Get count of active alerts"""
        return cls.get_active_alerts(severity, category).count()


class AlertSubscription(models.Model):
    """User subscriptions for alert notifications"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alert_subscriptions')
    category = models.CharField(max_length=20, choices=SystemAlert.CATEGORY_CHOICES)
    severity_min = models.CharField(max_length=10, choices=SystemAlert.SEVERITY_CHOICES, 
                                  default='warning', help_text="Minimum severity to notify")
    is_email_enabled = models.BooleanField(default=True)
    is_web_enabled = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'category']
    
    def __str__(self):
        return f"{self.user.username} - {self.category} alerts"


class AlertLog(models.Model):
    """Log of all alert notifications sent"""
    
    alert = models.ForeignKey(SystemAlert, on_delete=models.CASCADE, related_name='notification_logs')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=20, choices=[
        ('email', 'Email'),
        ('web', 'Web'),
        ('sms', 'SMS'),
        ('webhook', 'Webhook'),
    ])
    sent_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(null=True, blank=True)
    
    class Meta:
        ordering = ['-sent_at']
    
    def __str__(self):
        return f"{self.alert.title} → {self.user.username} ({self.notification_type})"
