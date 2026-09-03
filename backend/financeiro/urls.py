# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/urls.py

from django.urls import path
from financeiro import views

app_name = 'financeiro'

urlpatterns = [
    path('', views.fechamento_agregados_view, name='fechamento_agregados'),
    path('api/gerar/', views.api_gerar_fechamento, name='api_gerar_fechamento'),
    path('api/linha/salvar/', views.api_salvar_linha, name='api_salvar_linha'),
    path('api/resumo/salvar/', views.api_salvar_resumo, name='api_salvar_resumo'),
    path('api/dados-bancarios/salvar/', views.api_salvar_dados_bancarios, name='api_salvar_dados_bancarios'),
    path('api/tarifa/salvar/', views.api_salvar_tarifa, name='api_salvar_tarifa'),
    path('api/filial/salvar-uf/', views.api_salvar_uf_filial, name='api_salvar_uf_filial'),
    path('api/ocorrencias/salvar/', views.api_salvar_config_ocorrencias, name='api_salvar_config_ocorrencias'),
    path('api/cliente/salvar-filial/', views.api_salvar_cliente_filial, name='api_salvar_cliente_filial'),
    path('api/cliente/sincronizar/', views.api_sincronizar_clientes, name='api_sincronizar_clientes'),
    path('exportar-excel/', views.api_exportar_excel, name='exportar_excel'),
]
