from django.urls import path
from . import views

app_name = 'sac_mobile'

urlpatterns = [
    path('', views.app_view, name='app_home'),
    path('manifest_sac.json', views.serve_manifest_sac, name='manifest_sac'),
    path('serviceworker_sac.js', views.serve_sw_sac, name='serviceworker_sac'),
    path('api/search-nf/', views.api_search_nf, name='api_search_nf'),
    path('api/check-comprovante/', views.api_check_comprovante_sac, name='api_check_comprovante_sac'),
    path('api/baixa/', views.api_registrar_baixa_sac, name='api_registrar_baixa_sac'),
    
    # NOVAS ROTAS DE AUDITORIA
    path('api/auditoria/manifestos/', views.api_listar_manifestos_auditoria_sac, name='api_listar_manifestos_auditoria'),
    path('api/auditoria/manifesto/<int:manifesto_id>/notas/', views.api_detalhes_manifesto_auditoria_sac, name='api_detalhes_manifesto_auditoria'),
    path('api/auditoria/baixa/', views.api_registrar_baixa_auditoria_sac, name='api_registrar_baixa_auditoria'),
    
    # NOVAS ROTAS DE REBUSCA (GESTÃO SAC)
    path('api/configuracao/rebusca/', views.api_config_rebusca, name='api_config_rebusca'),
    path('api/configuracao/rebusca/agora/', views.api_rebusca_agora, name='api_rebusca_agora'),
]
