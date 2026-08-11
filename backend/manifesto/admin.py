from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib.admin import ModelAdmin
import json
from .models import (
    Manifesto, NotaFiscal, Ocorrencia, BaixaNF, 
    HistoricoOcorrencia, ManifestoBuscaLog, WebhookEventoManifestoESL, WebhookTokenControl,
    LogBaixaNfe, Frete
)
from manifesto.tasks import enviar_baixa_esl_task

@admin.register(WebhookEventoManifestoESL)
class WebhookEventoManifestoESLAdmin(admin.ModelAdmin):

    # 📋 LISTAGEM
    list_display = (
        "id",
        "origem",
        "tipo",
        "numero_manifesto",
        "status_badge",
        "created_at",
        "processed_at",
    )

    # 🔍 FILTROS
    list_filter = (
        "origem",
        "tipo",
        "status",
        "created_at",
    )

    # 🔎 BUSCA
    search_fields = (
        "numero_manifesto",
        "tipo",
        "origem",
        "payload",
        "erro",
    )

    # 🔒 SOMENTE LEITURA
    readonly_fields = (
        "origem",
        "tipo",
        "numero_manifesto",
        "created_at",
        "processed_at",
        "payload_formatado",
        "erro",
    )

    # 📂 ORGANIZAÇÃO DO FORM
    fieldsets = (
        ("Identificação", {
            "fields": ("origem", "tipo", "numero_manifesto", "status")
        }),
        ("Payload recebido", {
            "fields": ("payload_formatado",),
        }),
        ("Processamento", {
            "fields": ("erro", "created_at", "processed_at"),
        }),
    )

    # ⬇️ ORDENAR
    ordering = ("-created_at",)

    # ⚙️ AÇÕES
    actions = ["marcar_como_processado", "marcar_como_erro"]

    # 🎨 STATUS COM COR
    def status_badge(self, obj):
        cores = {
            "PENDENTE": "#f0ad4e",
            "PROCESSADO": "#5cb85c",
            "ERRO": "#d9534f",
        }
        cor = cores.get(obj.status, "#777")
        return format_html(
            '<span style="color: white; background-color: {}; padding: 4px 8px; border-radius: 6px;">{}</span>',
            cor,
            obj.status
        )
    status_badge.short_description = "Status"

    # 🧾 JSON FORMATADO
    def payload_formatado(self, obj):
        try:
            return format_html(
                "<pre style='max-height:500px; overflow:auto'>{}</pre>",
                json.dumps(obj.payload, indent=2, ensure_ascii=False)
            )
        except Exception:
            return obj.payload

    payload_formatado.short_description = "Payload (JSON)"

    # ⚙️ AÇÕES
    def marcar_como_processado(self, request, queryset):
        queryset.update(
            status="PROCESSADO",
            processed_at=timezone.now()
        )
    marcar_como_processado.short_description = "Marcar como PROCESSADO"

    def marcar_como_erro(self, request, queryset):
        queryset.update(status="ERRO")
    marcar_como_erro.short_description = "Marcar como ERRO"
@admin.register(Manifesto)
class ManifestoAdmin(ModelAdmin):
    # 'veiculo' foi removido pois não existe no seu model Manifesto
    list_display = ("numero_manifesto", "motorista", "status", "data_criacao")
    list_filter = ("status", "finalizado")
    search_fields = ("numero_manifesto", "motorista__nome_completo")

@admin.register(Frete)
class FreteAdmin(ModelAdmin):
    list_display = ("freight_id_tms", "numero_cte", "modal", "remetente", "criado_em")
    search_fields = ("freight_id_tms", "numero_cte", "chave_cte", "remetente")
    list_filter = ("modal", "criado_em")

@admin.register(NotaFiscal)
class NotaFiscalAdmin(ModelAdmin):
    list_display = ("numero_nota", "manifesto", "destinatario", "status")
    search_fields = ("numero_nota", "chave_acesso", "destinatario")
    list_filter = ("status",)

@admin.register(Ocorrencia)
class OcorrenciaAdmin(ModelAdmin):
    list_display = ("codigo_tms", "codigo_referencia", "descricao", "tipo", "is_coleta", "is_entrega")
    search_fields = ("codigo_tms", "codigo_referencia", "descricao")
    list_filter = ("tipo", "is_coleta", "is_entrega")

@admin.register(HistoricoOcorrencia)
class HistoricoOcorrenciaAdmin(ModelAdmin):
    # Alterado para os campos existentes no model
    list_display = ("nota_fiscal", "codigo_tms", "data_ocorrencia", "manifesto_evento")
    list_filter = ("data_ocorrencia",)

@admin.register(ManifestoBuscaLog)
class ManifestoBuscaLogAdmin(ModelAdmin):
    # Ajustado para os campos reais: 'criado_em' e 'status'
    list_display = ("numero_manifesto", "motorista", "status", "criado_em")
    list_filter = ("status", "criado_em")
    search_fields = ("numero_manifesto", "motorista__nome_completo")

@admin.register(BaixaNF)
class BaixaNFAdmin(ModelAdmin):
    list_display = ("get_nf", "tipo", "status_integracao", "data_baixa", "ver_mapa")
    list_filter = ("processado_tms", "tipo", "data_baixa")
    readonly_fields = ("data_integracao", "log_erro_tms", "data_baixa")
    
    actions = ["forcar_reintegracao"]

    def status_integracao(self, obj):
        if obj.processado_tms:
            return format_html('<span style="color: #10b981; font-weight: bold;">✅ Integrado</span>')
        if obj.log_erro_tms:
            return format_html('<span style="color: #ef4444; font-weight: bold;" title="{}">❌ Erro</span>', obj.log_erro_tms)
        return format_html('<span style="color: #f59e0b; font-weight: bold;">⏳ Aguardando</span>')
    status_integracao.short_description = "Status ESL"

    def get_nf(self, obj):
        return f"NF {obj.nota_fiscal.numero_nota}"
    get_nf.short_description = "Nota Fiscal"

    def ver_mapa(self, obj):
        if obj.latitude and obj.longitude:
            url = f"https://www.google.com/maps?q={obj.latitude},{obj.longitude}"
            return format_html('<a href="{}" target="_blank">📍 Ver Local</a>', url)
        return "-"
    ver_mapa.short_description = "Mapa"

    def forcar_reintegracao(self, request, queryset):
        for baixa in queryset:
            enviar_baixa_esl_task.delay(baixa.id)
        self.message_user(request, "Integração disparada para os itens selecionados.")
    forcar_reintegracao.short_description = "Re-enviar para TMS ESL"

@admin.register(WebhookTokenControl)
class WebhookTokenControlAdmin(ModelAdmin):
    list_display = ("user", "total_mes_atual", "limite_mensal", "ativo", "data_atualizacao")
    list_filter = ("ativo", "data_atualizacao")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("data_atualizacao",)

@admin.register(LogBaixaNfe)
class LogBaixaNfeAdmin(ModelAdmin):
    list_display = ("numero_nota", "manifesto_numero", "tipo", "lido", "criado_em")
    list_filter = ("tipo", "lido", "criado_em")
    search_fields = ("numero_nota", "manifesto_numero", "mensagem")
    readonly_fields = ("criado_em",)
    ordering = ("-criado_em",)

