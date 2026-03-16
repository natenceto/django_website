"""
Admin models for system configuration and settings.
Stored in SQLite database for user/admin management.
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class SystemSettings(models.Model):
    """
    Global system settings for platform configuration.
    Singleton model - should only have one instance.
    """
    
    # Display settings
    site_name = models.CharField(
        max_length=100,
        default='RENEW EV Charging Platform',
        help_text='Platform name displayed throughout the system'
    )
    site_description = models.TextField(
        default='Renewable Energy EV Charging Management System',
        help_text='Platform description'
    )
    
    # Charging settings
    default_power_limit_kw = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=7.4,
        validators=[MinValueValidator(0.1), MaxValueValidator(350)],
        help_text='Default power limit for new charging sessions (kW)'
    )
    
    min_session_duration_minutes = models.IntegerField(
        default=5,
        validators=[MinValueValidator(1)],
        help_text='Minimum charging session duration (minutes)'
    )
    
    session_idle_timeout_minutes = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5)],
        help_text='Auto-disconnect after idle time (minutes)'
    )
    
    # WebSocket settings
    websocket_heartbeat_seconds = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text='WebSocket heartbeat interval (seconds)'
    )
    
    websocket_timeout_seconds = models.IntegerField(
        default=300,
        validators=[MinValueValidator(60), MaxValueValidator(3600)],
        help_text='WebSocket connection timeout (seconds)'
    )
    
    # Energy management
    enable_solar_optimization = models.BooleanField(
        default=True,
        help_text='Enable solar-based charging optimization'
    )
    
    solar_optimization_threshold_percent = models.IntegerField(
        default=70,
        validators=[MinValueValidator(10), MaxValueValidator(100)],
        help_text='Minimum solar generation % to enable optimization'
    )
    
    # System health
    enable_monitoring = models.BooleanField(
        default=True,
        help_text='Enable system health monitoring'
    )
    
    monitoring_interval_seconds = models.IntegerField(
        default=300,
        validators=[MinValueValidator(60)],
        help_text='Health check interval (seconds)'
    )
    
    # Audit & Logging
    enable_audit_logging = models.BooleanField(
        default=True,
        help_text='Enable detailed audit logging'
    )
    
    log_retention_days = models.IntegerField(
        default=90,
        validators=[MinValueValidator(7)],
        help_text='Retain logs for N days'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(
        max_length=100,
        blank=True,
        help_text='Last user to modify settings'
    )
    
    class Meta:
        verbose_name = 'System Settings'
        verbose_name_plural = 'System Settings'
    
    def __str__(self):
        return f'{self.site_name} - Settings'
    
    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
    
    @classmethod
    def load(cls):
        """Load settings (alias for get_settings)."""
        return cls.get_settings()


class AuditLog(models.Model):
    """
    Audit trail for system actions and configuration changes.
    """
    
    ACTION_CHOICES = [
        ('create', 'Created'),
        ('update', 'Updated'),
        ('delete', 'Deleted'),
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('settings_change', 'Settings Changed'),
        ('permission_change', 'Permission Changed'),
    ]
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.CharField(max_length=150, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=255, blank=True)
    description = models.TextField()
    
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
        ]
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
    
    def __str__(self):
        return f'{self.action} - {self.user} ({self.timestamp})'
