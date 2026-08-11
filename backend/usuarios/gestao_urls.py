# usuarios/gestao_urls.py
from django.urls import path
from .gestao_views import (
    gestao_usuarios_page,
    api_listar_usuarios,
    api_criar_usuario,
    api_editar_usuario,
    api_deletar_usuario,
    api_salvar_permissoes,
)

app_name = 'gestao'

urlpatterns = [
    path('usuarios/', gestao_usuarios_page, name='gestao_usuarios'),
    path('api/usuarios/', api_listar_usuarios, name='api_listar'),
    path('api/usuarios/criar/', api_criar_usuario, name='api_criar'),
    path('api/usuarios/<int:usuario_id>/editar/', api_editar_usuario, name='api_editar'),
    path('api/usuarios/<int:usuario_id>/deletar/', api_deletar_usuario, name='api_deletar'),
    path('api/usuarios/<int:usuario_id>/permissoes/', api_salvar_permissoes, name='api_permissoes'),
]
