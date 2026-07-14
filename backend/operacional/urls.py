# operacional/urls.py
from django.urls import path
from operacional.views import DashboardView, login_operacional_view, NotasFiscaisListView ,detalhes_nota_fiscal_view, ManifestosMonitoramentoView, MotoristasPerformanceView, ExportMotoristasPerformanceExcel
from operacional.rotas import buscar_e_importar_nfe, listar_manifestos_select, sincronizar_nota_tms_view, api_rastreio_manifesto
from operacional.notifications import api_notificacoes_erros, api_marcar_notificacoes_lidas, api_marcar_notificacao_lida, api_logs_baixa_nfe
from operacional import views

app_name = 'operacional'


urlpatterns = [
    # Coloque o login na raiz ou em /login/
    path('login/', login_operacional_view, name='login_operacional'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('logout/', views.logout_operacional_view, name='logout_operacional'),
    path('notas-fiscais/', NotasFiscaisListView.as_view(), name='notas_fiscais'),
    path('api/manifesto/detalhes-nota/<int:nota_id>/', detalhes_nota_fiscal_view, name='detalhes_nota_fiscal'),
    path('api/manifesto/buscar-importar/', buscar_e_importar_nfe, name='buscar_e_importar_nfe'),
    path('manifesto/', ManifestosMonitoramentoView.as_view(), name='manifesto_detalhes'),
    path('api/manifesto/sincronizar-nota/<int:nota_id>/', sincronizar_nota_tms_view, name='sincronizar_nota_tms'),
    path('api/manifesto/listar-para-select/', listar_manifestos_select, name='listar_manifestos_select'),
    path('api/manifesto/detalhes-modal/<int:manifesto_id>/', views.detalhes_manifesto_modal_view, name='detalhes_manifesto_modal'),
    path('api/manifesto/editar-modal/<int:manifesto_id>/', views.editar_manifesto_modal_view, name='editar_manifesto_modal'),
    path('api/manifesto/salvar-edicao/<int:manifesto_id>/', views.salvar_edicao_manifesto_view, name='salvar_edicao_manifesto'),
    path('api/manifesto/sincronizar/<int:manifesto_id>/', views.sincronizar_manifesto_operacional_view, name='sincronizar_manifesto_operacional'),
    path('api/manifesto/deletar/<int:manifesto_id>/', views.deletar_manifesto_operacional_view, name='deletar_manifesto_operacional'),
    path('api/nota-fiscal/deletar/<int:nota_id>/', views.deletar_nota_fiscal_view, name='deletar_nota_fiscal'),
    path('api/nota-fiscal/deletar-ocorrencia/<int:nota_id>/', views.deletar_ocorrencia_view, name='deletar_ocorrencia'),
    path('motoristas/', MotoristasPerformanceView.as_view(), name='motoristas'),
    path('motoristas/exportar/excel/', ExportMotoristasPerformanceExcel.as_view(), name='motoristas_exportar_excel'),
    path('motoristas/cadastrar/', views.motorista_cadastrar, name='motorista_cadastrar'),
    path('motoristas/editar/', views.motorista_editar, name='motorista_editar'),
    path('motoristas/avisar-todos/', views.motoristas_avisar_massa, name='motoristas_avisar_massa'),
    path('usuarios/reset-senha/<int:motorista_id>/', views.enviar_redefinicao_senha_view, name='enviar_redefinicao_senha'),
    path('api/rastreio/<int:manifesto_id>/', api_rastreio_manifesto, name='api_rastreio_manifesto'),

    # Central de Ajuda
    path('suporte/', views.SuporteView.as_view(), name='suporte'),
    path('treinamentos/', views.TreinamentosView.as_view(), name='treinamentos'),
    path('api/treinamentos/registrar_view/<int:video_id>/', views.registrar_view_treinamento, name='registrar_view_treinamento'),
    path('api/treinamentos/avaliar/<int:video_id>/', views.avaliar_treinamento, name='avaliar_treinamento'),
    path('central-ajuda/', views.CentralAjudaView.as_view(), name='central_ajuda'),
    path('api/suporte/abrir_ticket_operacional/', views.abrir_ticket_operacional, name='abrir_ticket_operacional'),

    # Configurações do Sistema
    path('configuracao/', views.ConfiguracaoSistemaView.as_view(), name='configuracao_sistema'),
    path('api/configuracao/salvar/', views.salvar_configuracao_view, name='salvar_configuracao'),
    path('api/configuracao/buscar-grupos-whatsapp/', views.buscar_grupos_whatsapp_view, name='buscar_grupos_whatsapp'),

    # Notificações de Erros (Centro de Notificações Global)
    path('api/notificacoes/erros/', api_notificacoes_erros, name='api_notificacoes_erros'),
    path('api/notificacoes/marcar-lidas/', api_marcar_notificacoes_lidas, name='api_marcar_notificacoes_lidas'),
    path('api/notificacoes/marcar-lida/<int:notif_id>/', api_marcar_notificacao_lida, name='api_marcar_notificacao_lida'),
    path('api/logs-baixa-nfe/', api_logs_baixa_nfe, name='api_logs_baixa_nfe'),
]