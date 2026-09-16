# clientes/admin.py
from django.contrib import admin
from .models import UsuarioCliente, VinculoPagador


class VinculoPagadorInline(admin.TabularInline):
    """Inline para cadastrar vínculos de pagador diretamente na tela do cliente."""
    model = VinculoPagador
    extra = 1
    fields = ('pagador_nome', 'pagador_documento', 'ativo')


@admin.register(UsuarioCliente)
class UsuarioClienteAdmin(admin.ModelAdmin):
    list_display = ['nome_completo', 'cpf', 'email', 'ativo', 'criado_em', 'ultimo_acesso']
    list_filter = ['ativo']
    search_fields = ['nome_completo', 'cpf', 'email']
    readonly_fields = ['criado_em', 'ultimo_acesso']
    inlines = [VinculoPagadorInline]

    fieldsets = (
        ('Dados do Cliente', {
            'fields': ('nome_completo', 'cpf', 'email', 'telefone')
        }),
        ('Conta de Acesso', {
            'fields': ('user', 'ativo'),
            'description': 'O auth.User é criado automaticamente no primeiro login do cliente.'
        }),
        ('Informações do Sistema', {
            'fields': ('criado_em', 'ultimo_acesso'),
            'classes': ('collapse',)
        }),
    )


@admin.register(VinculoPagador)
class VinculoPagadorAdmin(admin.ModelAdmin):
    list_display = ['usuario_cliente', 'pagador_nome', 'pagador_documento', 'ativo', 'criado_em']
    list_filter = ['ativo']
    search_fields = ['pagador_nome', 'pagador_documento', 'usuario_cliente__nome_completo']
    autocomplete_fields = ['usuario_cliente']
