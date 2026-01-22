import os

# Set Django settings module FIRST, before any Django imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')

# Initialize Django ASGI application BEFORE importing any app modules
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

# Reset all station statuses to inactive on server startup
# This ensures stale "active" statuses from previous sessions are cleared
def reset_station_statuses():
    try:
        from renew_website.apps.charging_stations.models import Station, Connector
        # Reset all stations to inactive
        updated_stations = Station.objects.filter(status='active').update(status='inactive')
        # Reset all connectors to offline
        updated_connectors = Connector.objects.exclude(status='available').update(status='offline')
        if updated_stations or updated_connectors:
            print(f"Server startup: Reset {updated_stations} stations to inactive, {updated_connectors} connectors to offline")
    except Exception as e:
        print(f"Warning: Could not reset station statuses on startup: {e}")

reset_station_statuses()

# Now it's safe to import Django app modules (after Django is initialized)
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
import renew_website.apps.charging_stations.routing

# Custom WebSocket middleware with keep-alive
class WebSocketKeepAliveMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            # Set WebSocket keep-alive to 60 seconds
            scope['keep_alive'] = 60
        return await self.app(scope, receive, send)

application = ProtocolTypeRouter({
    'http': django_asgi_app,  # Django ASGI application
    'websocket': WebSocketKeepAliveMiddleware(
        AuthMiddlewareStack(
            AllowedHostsOriginValidator(
                URLRouter(
                    renew_website.apps.charging_stations.routing.websocket_urlpatterns
                )
            )
        )
    ),
})