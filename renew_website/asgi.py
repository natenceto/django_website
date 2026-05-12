import os

# Set Django settings module FIRST, before any Django imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')

# Initialize Django ASGI application BEFORE importing any app modules
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

if os.environ.get('RESET_STATION_STATE_ON_STARTUP', '').lower() in {'1', 'true', 'yes'}:
    try:
        from renew_website.tasks import reset_station_runtime_state

        reset_station_runtime_state.delay()
    except Exception as exc:
        print(f"Warning: Could not enqueue station runtime reset on startup: {exc}")

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