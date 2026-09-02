from django.urls import path
from .views import AuditoriaDashboardView, RegistrarBaixaManualSACView, AuditoriaDetalhes360View

app_name = 'auditoria'

urlpatterns = [
    path('painel/', AuditoriaDashboardView.as_view(), name='dashboard'),
    path('api/baixa-sac/', RegistrarBaixaManualSACView.as_view(), name='baixa_sac'),
    path('api/detalhes-360/<str:manifesto_id>/', AuditoriaDetalhes360View.as_view(), name='detalhes_360'),
]
