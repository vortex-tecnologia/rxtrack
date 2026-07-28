# mobile/views.py

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from usuarios.models import Motorista
from usuarios.models import Motorista
from manifesto.models import Ocorrencia
from configuracao.models import ConfiguracaoSistema
# Rota para a tela de Login (Acesso público)
@never_cache
def login_view(request):
    """Serve a página de login para o PWA."""
    # O caminho do template é relativo à sua pasta 'templates'
    return render(request, 'aplicativo/login_motorista/login.html')


# Rota para a tela principal do PWA (Requer autenticação)
def app_view(request):
    if request.user.is_authenticated:
        motorista = getattr(request.user, 'motorista_perfil', None)
        if motorista:
            tipo = getattr(motorista, 'tipo_usuario', 'MOTORISTA')
            if tipo == 'SAC' and getattr(motorista, 'is_sac_mobile', False):
                return redirect('/app-sac/')
            elif tipo in ['OPERACIONAL', 'SAC'] or request.user.is_staff or request.user.is_superuser:
                return redirect('/dashboard/')
        elif request.user.is_staff or request.user.is_superuser:
            return redirect('/dashboard/')

    # Ocorrências de sucesso (Entrega)

    sucesso = Ocorrencia.objects.filter(codigo_tms__in=['1', '2']).order_by('codigo_tms')
    
    # Ocorrências de problema (Não Entrega) - Excluímos a 1 e 2 e filtramos por is_entrega=True
    problemas = Ocorrencia.objects.filter(is_entrega=True).exclude(codigo_tms__in=['1', '2']).order_by('codigo_tms')

    # Cia aera e rodoviaria
    cias = Ocorrencia.objects.filter(codigo_tms__in=['50', '51']).order_by('codigo_tms')
    
    config = ConfiguracaoSistema.load()
    
    return render(request, 'aplicativo/manifesto.html', {
        'sucesso': sucesso,
        'problemas': problemas,
        'cia': cias,
        'configuracao': config,
    })
# Nota: A autenticação (login_required) aqui é apenas para evitar que 
# a página seja vista. A verdadeira segurança da aplicação está nas 
# Views da API, que requerem o token JWT.

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from mobile.models import WebPushSubscription


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_webpush_token(request):
    try:
        sub = request.data.get('subscription')

        if not sub:
            return Response({"error": "Subscription não enviada"}, status=400)

        endpoint = sub.get('endpoint')
        keys = sub.get('keys', {})

        p256dh = keys.get('p256dh')
        auth = keys.get('auth')

        if not endpoint or not p256dh or not auth:
            return Response({"error": "Dados incompletos do subscription"}, status=400)

        obj, created = WebPushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": p256dh,
                "auth": auth,
                "browser": request.META.get('HTTP_USER_AGENT', ''),
                "group": request.data.get('group', 'motoristas')
            }
        )

        return Response({"message": "Salvo com sucesso"})

    except Exception as e:
        return Response({"error": str(e)}, status=400)
