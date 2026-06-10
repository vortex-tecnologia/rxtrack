from django.contrib import admin
from .models import TicketSuporte, MensagemSuporte, VideoTreinamento

class MensagemSuporteInline(admin.TabularInline):
    model = MensagemSuporte
    extra = 0
    readonly_fields = ('created_at',)
    can_delete = False

@admin.register(TicketSuporte)
class TicketSuporteAdmin(admin.ModelAdmin):
    list_display = ('id', 'motorista', 'filial', 'categoria', 'status', 'created_at')
    list_filter = ('status', 'categoria', 'filial')
    search_fields = ('motorista__nome_completo', 'motorista__cpf')
    inlines = [MensagemSuporteInline]

@admin.register(VideoTreinamento)
class VideoTreinamentoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'visualizacoes', 'likes', 'dislikes', 'ativo', 'created_at')
    list_filter = ('ativo',)
    search_fields = ('titulo', 'descricao')
    readonly_fields = ('visualizacoes', 'likes', 'dislikes')
