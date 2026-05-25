from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Aceita uma filial_id alfanumerica com hifens (slug) ou a string literar 'todas'
    re_path(r'ws/painel-logistico/(?:(?P<filial_id>[\w\-]+)/)?$', consumers.MonitoramentoConsumer.as_asgi()),
]