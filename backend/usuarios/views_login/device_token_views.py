"""
Views para Auto-Login via Device Token (Exclusivo APK).
Não altera nenhuma view existente do sistema.
"""
import secrets
import logging
from django.contrib.auth import login
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from usuarios.models import DeviceToken

logger = logging.getLogger(__name__)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def auto_login_device(request):
    """
    Rota chamada pelo index.html do APK ao abrir o app.
    Recebe o device_token como query param, valida e cria sessão Django.
    O initAuth() do authFetch.js cuida do resto (gera JWT a partir da sessão).
    
    Fluxo: APK abre → lê device_token do SharedPreferences → redireciona para cá
    """
    dt = request.GET.get('dt')
    
    if not dt:
        logger.warning("[Auto-Login] Chamado sem device token.")
        return redirect('/login/')
    
    try:
        device = DeviceToken.objects.select_related('user').get(token=dt, ativo=True)
    except DeviceToken.DoesNotExist:
        logger.warning(f"[Auto-Login] Device token inválido ou desativado: {dt[:8]}...")
        return redirect('/login/')
    
    # Atualiza timestamp de último uso
    device.ultimo_uso = timezone.now()
    device.save(update_fields=['ultimo_uso'])
    
    # Cria sessão Django para o usuário (seta cookie sessionid)
    login(request, device.user)
    logger.info(f"[Auto-Login] Sessão criada para {device.user.username} via device token.")
    
    # Redireciona para o app do motorista
    return redirect('/app/')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def criar_device_token(request):
    """
    Chamado pelo login.js APÓS login bem-sucedido, SOMENTE dentro do APK.
    Gera um device_token único e retorna para o JS salvar no SharedPreferences.
    
    Se o usuário já tiver um device_token ativo, reutiliza ele 
    (para não criar tokens infinitos a cada login).
    """
    user = request.user
    device_info = request.data.get('device_info', 'APK Android')
    
    # Tenta reutilizar token existente ativo
    existing = DeviceToken.objects.filter(user=user, ativo=True).first()
    if existing:
        existing.device_info = device_info
        existing.save(update_fields=['device_info', 'ultimo_uso'])
        return Response({
            'device_token': existing.token,
            'mensagem': 'Token existente reutilizado.'
        })
    
    # Cria novo token
    token = secrets.token_hex(32)  # 64 caracteres hexadecimais
    DeviceToken.objects.create(
        user=user,
        token=token,
        device_info=device_info
    )
    
    logger.info(f"[Device Token] Criado para {user.username}")
    
    return Response({
        'device_token': token,
        'mensagem': 'Device token criado com sucesso.'
    }, status=status.HTTP_201_CREATED)
