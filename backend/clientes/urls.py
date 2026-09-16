# clientes/urls.py
from django.urls import path
from . import views

app_name = 'clientes'

urlpatterns = [
    # Dashboard principal do portal do cliente
    path('', views.portal_cliente_view, name='portal'),

    # APIs de dados
    path('api/cargas/', views.api_cargas_cliente, name='api_cargas'),
    path('api/carga/<int:nota_id>/', views.api_detalhe_carga, name='api_detalhe'),
    path('api/exportar/', views.api_exportar_excel, name='api_exportar'),

    # API de busca de pagadores (usada pela gestão de usuários)
    path('api/buscar-pagadores/', views.api_buscar_pagadores, name='api_buscar_pagadores'),
]
