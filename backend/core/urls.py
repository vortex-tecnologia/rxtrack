# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static # Necessário para arquivos de mídia
from django.views.generic import RedirectView
from django.http import HttpResponse
from usuarios.views_login.auth_views import login_sac_mobile_view
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('capacitor.js', lambda r: HttpResponse("", content_type="application/javascript")),
    # Redireciona a raiz (/) para /login/
    path('', RedirectView.as_view(url='/login/', permanent=True)),
    path('admin/', admin.site.urls),
    
    # Rota Exclusiva de Login do SAC
    path('login-sac/', login_sac_mobile_view, name='login_sac_mobile'),
    
    # Rota para redefinição de senha via email
    path('redefinir-senha/<uidb64>/<token>/', include('usuarios.urls_reset')),
    
    path('api/auth/', include('core.rotas.auth')),
    path('auth/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),
    path('api/', include(('manifesto.urls', 'manifesto'), namespace='manifesto')),
    path('api/integracoes/', include(('integracoes.urls', 'integracoes'), namespace='integracoes')),
    
    # Documentação de API
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/swagger/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/docs/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('app/', include(('mobile.urls', 'mobile'), namespace='mobile')),
    path('app-sac/', include(('sac_mobile.urls', 'sac_mobile'), namespace='sac_mobile')),
    path('', include(('operacional.urls', 'operacional'), namespace='operacional')),
    path('ia/', include(('AgenteIa.urls', 'AgenteIa'), namespace='AgenteIa')),
    path('suporte/', include('suporte.urls')),
    path('auditoria/', include('auditoria.urls', namespace='auditoria')),
    path('', include('pwa.urls')),
    # Gestao de Usuarios
    path('gestao/', include('usuarios.gestao_urls')),
]

from django.urls import re_path
from django.views.static import serve

# Configuração para servir arquivos de mídia (Fotos de comprovantes/perfil) via Daphne
# IMPORTANTE: Em produção de grande escala, Nginx/S3 é melhor, mas para homologação com Daphne serve.
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]