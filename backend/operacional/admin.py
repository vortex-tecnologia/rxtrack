from django.contrib import admin
from django.utils.html import format_html
from .models import RegraClassificacaoErro, LogErroOperacional

@admin.register(RegraClassificacaoErro)
class RegraClassificacaoErroAdmin(admin.ModelAdmin):
    list_display = ['nome', 'pattern', 'severidade', 'publico_alvo', 'exibir_torre', 'prioridade', 'ativo']
    list_filter = ['severidade', 'publico_alvo', 'ativo', 'exibir_torre']
    list_editable = ['severidade', 'publico_alvo', 'exibir_torre', 'prioridade', 'ativo']
    search_fields = ['nome', 'pattern']
    ordering = ['prioridade']

@admin.register(LogErroOperacional)
class LogErroOperacionalAdmin(admin.ModelAdmin):
    list_display = ['criado_em', 'severidade_badge', 'categoria', 'titulo', 'filial', 'status']
    list_filter = ['severidade', 'categoria', 'status', 'filial']
    search_fields = ['titulo', 'descricao', 'manifesto_numero', 'nota_fiscal_numero', 'motorista_nome']
    readonly_fields = ['criado_em', 'atualizado_em', 'erro_raw', 'regra_aplicada']
    date_hierarchy = 'criado_em'

    def severidade_badge(self, obj):
        colors = {
            'CRITICO': '#ef4444',
            'ATENCAO': '#f59e0b',
            'INFO': '#3b82f6',
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold;">{}</span>',
            colors.get(obj.severidade, '#6b7280'),
            obj.get_severidade_display()
        )
    severidade_badge.short_description = 'Severidade'
