from django.db import models
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.utils import timezone
from .models_alerts import SystemAlert, AlertSubscription, AlertLog

class UserPosition(models.Model):
    name = models.CharField(max_length=64, unique=True)
    normalized_name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255)

    def __str__(self):
        return self.name
    

class UserProfile(models.Model):
    # owner
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    is_full_name_displayed = models.BooleanField(default=True)
    # details
    bio = models.CharField(max_length=500, blank=True, null=True)
    website = models.URLField(max_length=255, blank=True, null=True)
    position = models.ForeignKey(UserPosition, on_delete=models.SET_NULL, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"


class UserSession(models.Model):
    """Track user sessions for security and management"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_info = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-last_activity']
    
    def __str__(self):
        return f"{self.user.username} - {self.device_info or 'Unknown Device'}"
    
    @classmethod
    def get_active_sessions(cls, user):
        """Get all active sessions for a user"""
        return cls.objects.filter(user=user, is_active=True)
    
    @classmethod
    def terminate_session(cls, session_key):
        """Terminate a specific session"""
        try:
            session = cls.objects.get(session_key=session_key)
            session.is_active = False
            session.save()
            # Also delete from Django session table
            Session.objects.filter(session_key=session_key).delete()
            return True
        except cls.DoesNotExist:
            return False
    
    @classmethod
    def cleanup_expired_sessions(cls):
        """Clean up expired sessions"""
        expired_sessions = cls.objects.filter(
            last_activity__lt=timezone.now() - timezone.timedelta(days=30)
        )
        count = expired_sessions.count()
        expired_sessions.delete()
        return count