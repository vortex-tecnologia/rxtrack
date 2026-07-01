from django.contrib import admin
from .models import (
    WhatsAppProvedor,
    WhatsAppInstancia,
    ManifestoBotCache,
    NotificacaoManifestoLog
)


@admin.register(WhatsAppProvedor)
class WhatsAppProvedorAdmin(admin.ModelAdmin):
    """
    Admin para gerenciar provedores WhatsApp.
    Permite toggle rápido de ativo/prioridade direto na listagem.
    """
    list_display = ['nome', 'url_base', 'ativo', 'prioridade']
    list_editable = ['ativo', 'prioridade']
    list_display_links = ['nome']

    fieldsets = (
        ('🔌 Provedor', {
            'fields': ('nome', 'url_base', 'api_key'),
            'description': 'Dados de conexão com o servidor do provedor WhatsApp.'
        }),
        ('⚙️ Controle', {
            'fields': ('ativo', 'prioridade'),
            'description': (
                'Ative/desative o provedor instantaneamente. '
                'Se desativado, o sistema usará o próximo provedor por prioridade (menor número = maior prioridade).'
            )
        }),
    )


@admin.register(WhatsAppInstancia)
class WhatsAppInstanciaAdmin(admin.ModelAdmin):
    """
    Admin para vincular instâncias WhatsApp às filiais.
    Cada filial = 1 instância (1 número WhatsApp).
    """
    list_display = ['filial', 'provedor', 'nome_instancia', 'numero_whatsapp', 'ativo']
    list_editable = ['ativo']
    list_filter = ['provedor', 'ativo']
    list_display_links = ['filial']
    search_fields = ['filial__nome', 'nome_instancia', 'numero_whatsapp']

    fieldsets = (
        ('📍 Vínculo', {
            'fields': ('filial', 'provedor'),
            'description': 'Selecione a filial e qual provedor WhatsApp ela utilizará para envios.'
        }),
        ('📱 Dados da Instância', {
            'fields': ('nome_instancia', 'numero_whatsapp', 'api_token'),
            'description': (
                'Nome da instância = nome cadastrado no Evolution API / Z-API. '
                'Número no formato internacional: 5511999999999. '
                'Token da Instância é opcional. Se preenchido, será usado em vez da API Key Global.'
            )
        }),
        ('⚙️ Status', {
            'fields': ('ativo',),
        }),
    )


@admin.register(ManifestoBotCache)
class ManifestoBotCacheAdmin(admin.ModelAdmin):
    """
    Admin somente leitura para auditoria do cache de manifestos do TMS.
    """
    list_display = ['filial', 'data_referencia', 'total_manifestos', 'atualizado_em']
    list_filter = ['filial', 'data_referencia']
    readonly_fields = [
        'filial', 'data_referencia', 'payload_tms',
        'manifestos_encontrados', 'total_manifestos',
        'atualizado_em', 'criado_em'
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(NotificacaoManifestoLog)
class NotificacaoManifestoLogAdmin(admin.ModelAdmin):
    """
    Admin completo de auditoria — todas as mensagens enviadas pelo bot.
    """
    list_display = [
        'enviado_em', 'rodada_display', 'motorista',
        'manifesto', 'filial', 'tipo_mensagem',
        'provedor_usado', 'status'
    ]
    list_filter = ['status', 'provedor_usado', 'tipo_mensagem', 'rodada', 'filial', 'data_referencia']
    search_fields = ['motorista__nome_completo', 'manifesto__numero_manifesto', 'numero_destino']
    readonly_fields = [
        'motorista', 'manifesto', 'filial', 'data_referencia',
        'rodada', 'tipo_mensagem', 'mensagem_enviada',
        'provedor_usado', 'instancia_usada', 'numero_destino',
        'status', 'erro_detalhe', 'resposta_api', 'enviado_em'
    ]
    date_hierarchy = 'enviado_em'
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Rodada")
    def rodada_display(self, obj):
        HORARIOS = {1: '11h', 2: '12h', 3: '14h', 4: '15h', 5: '16h'}
        hora = HORARIOS.get(obj.rodada, '??')
        return f"R{obj.rodada} ({hora})"
