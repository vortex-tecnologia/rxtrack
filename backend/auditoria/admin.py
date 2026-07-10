from django.contrib import admin
from auditoria.models import LogExclusaoOcorrencia


@admin.register(LogExclusaoOcorrencia)
class LogExclusaoOcorrenciaAdmin(admin.ModelAdmin):
    list_display = [
        'data_exclusao', 'usuario_nome', 'nota_fiscal_numero',
        'manifesto_numero', 'motorista_nome', 'ocorrencia_descricao',
        'estava_integrado_tms'
    ]
    list_filter = ['estava_integrado_tms', 'data_exclusao']
    search_fields = [
        'nota_fiscal_numero', 'chave_acesso', 'manifesto_numero',
        'motorista_nome', 'usuario_nome', 'motivo_exclusao'
    ]
    readonly_fields = [
        'usuario', 'usuario_nome', 'nota_fiscal_id', 'nota_fiscal_numero',
        'chave_acesso', 'manifesto_numero', 'motorista_nome',
        'ocorrencia_codigo', 'ocorrencia_descricao', 'tipo_baixa',
        'estava_integrado_tms', 'motivo_exclusao', 'dados_baixa_json',
        'data_exclusao'
    ]
    date_hierarchy = 'data_exclusao'

    def has_add_permission(self, request):
        return False  # Logs não podem ser criados manualmente

    def has_delete_permission(self, request, obj=None):
        return False  # Logs não podem ser excluídos
