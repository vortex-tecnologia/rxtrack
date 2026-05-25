from django.contrib import admin
from .models import ConfiguracaoSistema


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
    """
    Admin bonito e organizado para a Configuração do Sistema.
    Impede criação de mais de 1 registro (Singleton).
    """

    fieldsets = (
        ('🔑 Tokens da API ESL', {
            'fields': ('token_analytics', 'token_invoices'),
            'description': 'Tokens de autenticação para a API da ESL Cloud.'
        }),
        ('🌐 Domínio e Reports', {
            'fields': ('dominio_esl', 'report_validacao', 'report_busca_nfe'),
            'description': 'Configurações de conexão com a plataforma ESL.'
        }),
        ('⚙️ Feature Flags - Ações Secundárias', {
            'fields': (
                'processar_yolo', 
                'processar_ocr', 
                'enviar_tms', 
                'enviar_email_falhas', 
                'emails_notificacao',
                'armazenar_foto_backup',
            ),
            'description': 'Liga/Desliga funções secundárias do sistema. Funções do motorista e salvamento no banco são sempre ativas.'
        }),
        ('🤖 Agente IA', {
            'fields': ('codigos_ocorrencia_yolo',),
            'description': 'Quais códigos de ocorrência TMS devem passar pelo processamento da IA (YOLO).'
        }),
        ('💬 SAC & Suporte', {
            'fields': ('habilitar_chat_sac',),
            'description': 'Controla a visibilidade do botão de chat no app do motorista.'
        }),
    )

    def has_add_permission(self, request):
        # Só permite adicionar se não existir nenhum registro
        return not ConfiguracaoSistema.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Nunca permite deletar
        return False

    def changelist_view(self, request, extra_context=None):
        # Se já existe, redireciona direto para o formulário de edição
        obj = ConfiguracaoSistema.load()
        from django.shortcuts import redirect
        return redirect(f'/admin/configuracao/configuracaosistema/{obj.pk}/change/')
