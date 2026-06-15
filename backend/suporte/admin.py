from django.contrib import admin
from .models import TicketSuporte, MensagemSuporte

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
