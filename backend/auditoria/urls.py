from django.urls import path
from .views import AuditoriaDashboardView, RegistrarBaixaManualSACView

app_name = 'auditoria'

urlpatterns = [
    path('painel/', AuditoriaDashboardView.as_view(), name='dashboard'),
    path('api/baixa-sac/', RegistrarBaixaManualSACView.as_view(), name='baixa_sac'),
]
