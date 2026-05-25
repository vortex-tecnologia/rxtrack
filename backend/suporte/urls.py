from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TicketSuporteViewSet, MensagemSuporteViewSet, PainelSACView

app_name = 'suporte'

router = DefaultRouter()
router.register(r'tickets', TicketSuporteViewSet, basename='ticket')
router.register(r'mensagens', MensagemSuporteViewSet, basename='mensagem')

urlpatterns = [
    path('painel/', PainelSACView.as_view(), name='painel_sac'),
    path('api/', include(router.urls)),
]
