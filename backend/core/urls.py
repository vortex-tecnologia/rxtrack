# core/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static # Necessário para arquivos de mídia
from django.views.generic import RedirectView
from usuarios.views_login.auth_views import login_sac_mobile_view

urlpatterns = [
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

# Configuração para servir arquivos de mídia (Fotos de comprovantes) em ambiente de desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)