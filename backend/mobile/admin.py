from django.contrib import admin
from .models import WebPushSubscription , BuscaDiariaManifestos , ManifestoNotificado

@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'endpoint', 'browser', 'group', 'created_at')
    search_fields = ('user__username', 'endpoint', 'browser', 'group')
    list_filter = ('browser', 'group', 'created_at')

@admin.register(BuscaDiariaManifestos)
class BuscaDiariaManifestosAdmin(admin.ModelAdmin):
    list_display = ('filial', 'data_criacao')
    search_fields = ('filial__nome',)
    list_filter = ('data_criacao',)

@admin.register(ManifestoNotificado)
class ManifestoNotificadoAdmin(admin.ModelAdmin):
    list_display = ('manifesto', 'motorista', 'ultima_notificacao')
    search_fields = ('manifesto', 'motorista__username')
    list_filter = ('ultima_notificacao',)