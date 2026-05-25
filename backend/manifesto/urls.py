# manifesto/urls.py
from django.urls import path
from manifesto.rotas.busca import (
    BuscarManifestoView,
    ImportarManifestoAdminView,
    CheckImportStatusView,
    ListarTodosLogsView
)
from manifesto.rotas.status import StatusBuscaManifestoView
from manifesto.rotas.iniciar_transporte import IniciarTransporteView
from manifesto.rotas.init import AppInitView
from manifesto.rotas.preview import StatusPreviewManifestoView
from manifesto.rotas.listagem import ListarNotasManifestoView
from manifesto.rotas.verificacao import VerificarManifestoAtivoView
from manifesto.rotas.baixa import RegistrarBaixaView, RegistrarBaixaOperacionalView
from manifesto.rotas.motorista_perfil import perfil_motorista
from manifesto.views import ManifestoFinalizacaoView
from manifesto.rotas.historicomanifestos import HistoricoManifestosView
from manifesto.rotas.sincronizarmanifesto import SincronizarManifestoView
from manifesto.rotas.webhook import webhook_tms
from manifesto.rotas.listagemocorrencias import ListarOcorrenciasView
from manifesto.rotas.views_painel import painel_monitoramento

urlpatterns = [
    path('manifesto/busca/', BuscarManifestoView.as_view()),
    path('manifesto/status/', StatusBuscaManifestoView.as_view()),
    path('manifesto/iniciar/', IniciarTransporteView.as_view()),
    path('app/init/', AppInitView.as_view()),
    path('manifesto/preview/', StatusPreviewManifestoView.as_view()),
    path('manifesto/notas/', ListarNotasManifestoView.as_view()),
    path('manifesto/verificar-ativo/', VerificarManifestoAtivoView.as_view()),
    path('manifesto/historico/', HistoricoManifestosView.as_view()),
    path('manifesto/registrar-baixa/', RegistrarBaixaView.as_view()),
    path('motorista/perfil/', perfil_motorista, name='motorista_perfil'),
    path('manifesto/finalizar/', ManifestoFinalizacaoView.as_view()),
    path('manifesto/sincronizar/', SincronizarManifestoView.as_view()),
    path('webhook/tms/', webhook_tms, name='webhook_tms'),
    path('manifesto/ocorrencias/', ListarOcorrenciasView.as_view()),
    path('manifesto/baixa-operacional/', RegistrarBaixaOperacionalView.as_view()),
    path('manifesto/importar-admin/', ImportarManifestoAdminView.as_view()),
    path('manifesto/importar-status/<int:log_id>/', CheckImportStatusView.as_view(), name='importar_manifesto_status'),
    path('manifesto/importar-logs/', ListarTodosLogsView.as_view(), name='listar_todos_logs'),
    path('painel/monitoramento/', painel_monitoramento, name='painel_monitoramento'),
]
