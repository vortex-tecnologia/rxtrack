from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/suporte/ticket/(?P<ticket_id>\d+)/$', consumers.SupportConsumer.as_asgi()),
    re_path(r'ws/suporte/filial/(?P<filial_id>\d+)/$', consumers.SupportConsumer.as_asgi()),
]
