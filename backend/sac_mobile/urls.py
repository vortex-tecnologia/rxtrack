from django.urls import path
from . import views

app_name = 'sac_mobile'

urlpatterns = [
    path('', views.app_view, name='app_home'),
    path('api/search-nf/', views.api_search_nf, name='api_search_nf'),
    path('api/check-comprovante/', views.api_check_comprovante_sac, name='api_check_comprovante_sac'),
    path('api/baixa/', views.api_registrar_baixa_sac, name='api_registrar_baixa_sac'),
    
    # NOVAS ROTAS DE AUDITORIA
    path('api/auditoria/manifestos/', views.api_listar_manifestos_auditoria_sac, name='api_listar_manifestos_auditoria'),
    path('api/auditoria/manifesto/<int:manifesto_id>/notas/', views.api_detalhes_manifesto_auditoria_sac, name='api_detalhes_manifesto_auditoria'),
    path('api/auditoria/baixa/', views.api_registrar_baixa_auditoria_sac, name='api_registrar_baixa_auditoria'),
]
