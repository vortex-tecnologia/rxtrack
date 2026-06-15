from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import VideoTreinamento

@admin.register(VideoTreinamento)
class VideoTreinamentoAdmin(ModelAdmin):
    list_display = ('titulo', 'url_youtube', 'visualizacoes', 'likes', 'dislikes', 'ativo', 'created_at')
    list_filter = ('ativo', 'created_at')
    search_fields = ('titulo', 'descricao')
