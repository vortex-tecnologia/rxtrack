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

urlpatterns = [
    path('verificar-cpf/', VerificarCPFView.as_view(), name='verificar-cpf'),
    path('primeiro-acesso/', PrimeiroAcessoView.as_view(), name='primeiro-acesso'),
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('me/', MeView.as_view(), name='me'),
    path('login-session/', LoginSessionView.as_view(), name='login_session'),
    path('me-session/', MeSessionView.as_view(), name='me_session'),
    path('logout-session/', LogoutSessionView.as_view(), name='logout_session'),
]
