from django.contrib import admin
from django.contrib.admin import ModelAdmin
from .models import HistoricoBaixaSAC

@admin.register(HistoricoBaixaSAC)
class HistoricoBaixaSACAdmin(ModelAdmin):
    list_display = ('id', 'chave_acesso', 'freight_id', 'numero_nota', 'ocorrencia_codigo', 'usuario', 'status_tms', 'ia_yolo_status', 'data_criacao')
    list_filter = ('status_tms', 'ia_yolo_status', 'data_criacao', 'usuario')
    search_fields = ('chave_acesso', 'freight_id', 'numero_nota', 'ocorrencia_codigo')
    readonly_fields = ('data_criacao',)
    
    # Organize in fieldsets
    fieldsets = (
        ('Identificação', {
            'fields': ('usuario', 'chave_acesso', 'freight_id', 'numero_nota')
        }),
        ('Ocorrência', {
            'fields': ('ocorrencia_codigo', 'somente_comprovante', 'observacao')
        }),
        ('Mídia', {
            'fields': ('url_foto_original', 'url_foto_recortada', 'ia_yolo_status')
        }),
        ('Status', {
            'fields': ('status_tms', 'log_erro_tms', 'data_criacao')
        }),
    )
