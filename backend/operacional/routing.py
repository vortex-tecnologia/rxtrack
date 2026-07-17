from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/torre-erros/(?P<filial_id>[\w\-]+)/$', consumers.TorreErrosConsumer.as_asgi()),
    re_path(r'ws/torre-erros/$', consumers.TorreErrosConsumer.as_asgi()),
]
