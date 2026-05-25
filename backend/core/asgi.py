# core/asgi.py
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
# Initialize Django ASGI early to populate the AppRegistry
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

import manifesto.routing
import suporte.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            manifesto.routing.websocket_urlpatterns +
            suporte.routing.websocket_urlpatterns
        )
    ),
})
