# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/admin.py

from django.contrib import admin
from financeiro.models import (
    ConfiguracaoFinanceiro, TarifaAgregado, FechamentoAgregado,
    LinhaFechamento, ResumoMotorista, DadosBancariosAgregado,
    ClienteBasePagadora
)


@admin.register(ClienteBasePagadora)
class ClienteBasePagadoraAdmin(admin.ModelAdmin):
    list_display = ('nome', 'documento', 'filial_responsavel', 'atualizado_em')
    list_filter = ('filial_responsavel',)
    search_fields = ('nome', 'documento')



@admin.register(ConfiguracaoFinanceiro)
class ConfiguracaoFinanceiroAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'atualizado_em', 'atualizado_por')
    filter_horizontal = ('ocorrencias_pagamento_entrega', 'ocorrencias_pagamento_coleta')


@admin.register(TarifaAgregado)
class TarifaAgregadoAdmin(admin.ModelAdmin):
    list_display = ('filial', 'valor_diaria', 'valor_por_entrega', 'valor_por_coleta', 'vigencia_inicio')
    list_filter = ('filial', 'vigencia_inicio')
    search_fields = ('filial__nome',)


class LinhaFechamentoInline(admin.TabularInline):
    model = LinhaFechamento
    extra = 0
    readonly_fields = ('manifesto', 'motorista', 'data', 'total_dia')


class ResumoMotoristaInline(admin.TabularInline):
    model = ResumoMotorista
    extra = 0
    readonly_fields = ('motorista', 'total_servicos', 'total_final')


@admin.register(FechamentoAgregado)
class FechamentoAgregadoAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'periodo_inicio', 'periodo_fim', 'status', 'criado_em')
    list_filter = ('status', 'periodo_inicio')
    inlines = [ResumoMotoristaInline, LinhaFechamentoInline]


@admin.register(DadosBancariosAgregado)
class DadosBancariosAgregadoAdmin(admin.ModelAdmin):
    list_display = ('motorista', 'chave_pix', 'titular_pagamento')
    search_fields = ('motorista__nome_completo', 'motorista__cpf', 'chave_pix')
