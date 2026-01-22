from django.utils import timezone
from .models import UserSession
import user_agents


class SessionTrackingMiddleware:
    """Middleware to track user sessions"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Process request
        response = self.get_response(request)
        
        # Track session if user is authenticated
        if request.user.is_authenticated:
            self.track_session(request)
        
        return response
    
    def track_session(self, request):
        """Track or update user session"""
        session_key = request.session.session_key
        
        if not session_key:
            return
        
        # Get or create session record
        user_session, created = UserSession.objects.get_or_create(
            user=request.user,
            session_key=session_key,
            defaults={
                'ip_address': self.get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'device_info': self.get_device_info(request),
                'location': self.get_location_from_ip(request),
            }
        )
        
        if not created:
            # Update existing session
            user_session.last_activity = timezone.now()
            user_session.ip_address = self.get_client_ip(request)
            user_session.save()
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_device_info(self, request):
        """Extract device information from user agent"""
        user_agent_string = request.META.get('HTTP_USER_AGENT', '')
        user_agent_obj = user_agents.parse(user_agent_string)
        
        device = f"{user_agent_obj.os.family} - {user_agent_obj.browser.family}"
        if user_agent_obj.is_mobile:
            device = f"Mobile - {device}"
        elif user_agent_obj.is_tablet:
            device = f"Tablet - {device}"
        else:
            device = f"Desktop - {device}"
        
        return device
    
    def get_location_from_ip(self, request):
        """Get location from IP (mock implementation)"""
        # In production, you'd use a geolocation service
        ip = self.get_client_ip(request)
        
        # Mock locations for common IPs
        mock_locations = {
            '127.0.0.1': 'Localhost',
            '::1': 'Localhost',
            '192.168.1.1': 'Local Network',
            '10.0.0.1': 'Office Network',
        }
        
        return mock_locations.get(ip, 'Unknown Location')
