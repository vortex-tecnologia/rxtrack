from django.contrib import admin
from .models import Motorista, Filial


@admin.register(Motorista)
class MotoristaAdmin(admin.ModelAdmin):
    list_display = ('nome_completo', 'cpf', 'tipo_usuario', 'cargo', 'filial', 'permitir_upload_galeria')
    list_filter = ('tipo_usuario', 'cargo', 'filial', 'permitir_upload_galeria')
    list_editable = ('cargo', 'permitir_upload_galeria')
    search_fields = ('nome_completo', 'cpf')


admin.site.register(Filial)
