# usuarios/urls.py
# Vem de path('auth/', include(('usuarios.urls', 'usuarios'), namespace='usuarios')),
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from usuarios.views_login.auth_views import CustomTokenObtainPairView, LoginSessionView, MeSessionView, LogoutSessionView
from .views import PerfilMotoristaView, CustomTokenRefreshView, AtualizarFcmTokenView

urlpatterns = [
    # 1. Rota de Login Clássica (JWT)
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    
    # Rota de Login Nova (Sessão HTTP + JWT Oculto)
    path('login-session/', LoginSessionView.as_view(), name='login_session'),
    path('me-session/', MeSessionView.as_view(), name='me_session'),
    path('logout-session/', LogoutSessionView.as_view(), name='logout_session'),
    
    # 2. Rota de Renovação Clássica (JWT)
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    
    # 3. Rota de Validação/Perfil
    path('perfil/', PerfilMotoristaView.as_view(), name='motorista_perfil'),

    # 4. Rota para atualização de Token Firebase Push (APK Android)
    path('fcm-token/', AtualizarFcmTokenView.as_view(), name='atualizar_fcm_token'),
]