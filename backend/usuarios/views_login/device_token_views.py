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

from usuarios.models import DeviceToken, Motorista

logger = logging.getLogger(__name__)


def resolver_motorista(user):
    """
    Localiza o objeto Motorista associado a um User por todas as vias possíveis:
    1. OneToOne relation (user.motorista_perfil)
    2. ForeignKey (Motorista.objects.filter(user=user))
    3. Match por CPF (Motorista.objects.filter(cpf=user.username))
    """
    if not user:
        return None
    try:
        m = getattr(user, 'motorista_perfil', None)
        if m:
            return m
    except Exception:
        pass
    m = Motorista.objects.filter(user=user).first()
    if m:
        return m
    cpf_clean = str(user.username).replace('.', '').replace('-', '').strip()
    if cpf_clean:
        m = Motorista.objects.filter(cpf=cpf_clean).first()
        if m:
            if not m.user:
                try:
                    m.user = user
                    m.save(update_fields=['user'])
                except Exception:
                    pass
            return m
    return None


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def auto_login_device(request):
    """
    Rota chamada pelo index.html do APK ao abrir o app.
    Recebe o device_token (e opcionalmente o fcm_token) como query param, valida e cria sessão Django.
    O initAuth() do authFetch.js cuida do resto (gera JWT a partir da sessão).
    """
    dt = request.GET.get('dt')
    fcm_token = request.GET.get('fcm') or request.GET.get('fcm_token')
    
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
    
    # Se o FCM Token foi passado na URL do auto-login, atualiza o motorista imediatamente
    if fcm_token:
        try:
            motorista = resolver_motorista(device.user)
            if motorista:
                motorista.fcm_token = fcm_token.strip()
                motorista.fcm_token_atualizado_em = timezone.now()
                motorista.save(update_fields=['fcm_token', 'fcm_token_atualizado_em'])
                logger.info(f"[Auto-Login] FCM Token atualizado para {motorista.nome_completo} ({motorista.cpf}) via auto-login.")
            else:
                logger.warning(f"[Auto-Login] Não foi possível resolver motorista para user: {device.user.username}")
        except Exception as e:
            logger.error(f"[Auto-Login] Erro ao salvar FCM Token para motorista: {e}")

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
