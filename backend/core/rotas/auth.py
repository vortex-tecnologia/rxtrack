# core/urls/auth.py
from django.urls import path
from usuarios.views_login.auth_views import (
    VerificarCPFView,
    PrimeiroAcessoView,
    MeView,
    CustomTokenObtainPairView,
    LoginSessionView,
    MeSessionView,
    LogoutSessionView
)
from usuarios.views_login.device_token_views import auto_login_device, criar_device_token

from usuarios.views import AtualizarFcmTokenView

urlpatterns = [
    path('verificar-cpf/', VerificarCPFView.as_view(), name='verificar-cpf'),
    path('primeiro-acesso/', PrimeiroAcessoView.as_view(), name='primeiro-acesso'),
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('login-session/', LoginSessionView.as_view(), name='login_session'),
    path('me-session/', MeSessionView.as_view(), name='me_session'),
    path('logout-session/', LogoutSessionView.as_view(), name='logout_session'),
    # Auto-login APK (Device Token)
    path('auto-login/', auto_login_device, name='auto_login_device'),
    path('device-token/', criar_device_token, name='criar_device_token'),
    path('fcm-token/', AtualizarFcmTokenView.as_view(), name='fcm_token_api'),
]

