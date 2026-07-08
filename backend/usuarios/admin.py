from django.contrib import admin
from .models import Motorista, Filial, DeviceToken


@admin.register(Motorista)
class MotoristaAdmin(admin.ModelAdmin):
    list_display = ('nome_completo', 'cpf', 'tipo_usuario', 'cargo', 'filial', 'permitir_upload_galeria')
    list_filter = ('tipo_usuario', 'cargo', 'filial', 'permitir_upload_galeria')
    list_editable = ('cargo', 'permitir_upload_galeria')
    search_fields = ('nome_completo', 'cpf')
    readonly_fields = ('modelo_aparelho', 'memoria_ram')


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_info', 'ativo', 'criado_em', 'ultimo_uso')
    list_filter = ('ativo',)
    list_editable = ('ativo',)
    search_fields = ('user__username', 'device_info')
    readonly_fields = ('token', 'criado_em', 'ultimo_uso')


admin.site.register(Filial)
