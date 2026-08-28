from django.contrib import admin
from django.contrib import messages
from .models import Motorista, Filial, DeviceToken, NotificacaoPushLog
from common.fcm_service import enviar_notificacao_massa


@admin.action(description="📲 Enviar Notificação Push (Firebase FCM) aos selecionados")
def disparar_push_selecionados(modeladmin, request, queryset):
    from common.fcm_service import enviar_notificacao_massa
    res = enviar_notificacao_massa(
        motoristas_qs_ou_lista=queryset,
        titulo="📢 Aviso Importante RXTrack",
        mensagem="Você possui atualizações pendentes no aplicativo. Verifique seus manifestos.",
        tipo="MANUAL"
    )
    modeladmin.message_user(
        request,
        f"Envio finalizado! Sucessos: {res['sucessos']} | Falhas/Sem Token: {res['falhas']}",
        messages.SUCCESS if res['sucessos'] > 0 else messages.WARNING
    )


@admin.register(Motorista)
class MotoristaAdmin(admin.ModelAdmin):
    list_display = ('nome_completo', 'cpf', 'tipo_usuario', 'cargo', 'filial', 'tem_fcm_token', 'permitir_upload_galeria')
    list_filter = ('tipo_usuario', 'cargo', 'filial', 'permitir_upload_galeria')
    list_editable = ('cargo', 'permitir_upload_galeria')
    search_fields = ('nome_completo', 'cpf')
    readonly_fields = ('modelo_aparelho', 'memoria_ram', 'fcm_token_atualizado_em')
    actions = [disparar_push_selecionados]

    @admin.display(boolean=True, description="APK com FCM Push?")
    def tem_fcm_token(self, obj):
        return bool(obj.fcm_token)


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_info', 'ativo', 'criado_em', 'ultimo_uso')
    list_filter = ('ativo',)
    list_editable = ('ativo',)
    search_fields = ('user__username', 'device_info')
    readonly_fields = ('token', 'criado_em', 'ultimo_uso')


@admin.register(NotificacaoPushLog)
class NotificacaoPushLogAdmin(admin.ModelAdmin):
    list_display = ('motorista', 'titulo', 'tipo', 'sucesso', 'criado_em', 'response_message_id')
    list_filter = ('sucesso', 'tipo', 'criado_em')
    search_fields = ('motorista__nome_completo', 'titulo', 'mensagem', 'erro_detalhes')
    readonly_fields = ('criado_em', 'response_message_id', 'erro_detalhes')


@admin.register(Filial)
class FilialAdmin(admin.ModelAdmin):
    list_display = ('nome', 'id_filial_tms', 'operacao_ativa', 'cidade', 'uf', 'latitude', 'longitude', 'whatsapp_operacional', 'whatsapp_sac', 'horario_rebusca_esl')
    list_editable = ('operacao_ativa', 'whatsapp_operacional', 'whatsapp_sac')
    search_fields = ('nome', 'id_filial_tms', 'cidade', 'uf')
    list_filter = ('operacao_ativa', 'uf')
    fieldsets = (
        ('Identificação', {'fields': ('nome', 'id_filial_tms', 'horario_rebusca_esl')}),
        ('Endereço', {'fields': ('cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'uf')}),
        ('Geolocalização', {'fields': ('latitude', 'longitude'), 'description': 'Preenchido automaticamente ao salvar se o endereço estiver correto.'}),
        ('WhatsApp', {'fields': ('whatsapp_operacional', 'whatsapp_sac')}),
    )

