from django.contrib import admin
from .models import PostBlog


@admin.register(PostBlog)
class PostBlogAdmin(admin.ModelAdmin):
    list_display = ('versao', 'titulo', 'categoria', 'autor', 'data_publicacao', 'destaque', 'ativo', 'visualizacoes')
    list_filter = ('categoria', 'ativo', 'destaque', 'data_publicacao')
    search_fields = ('versao', 'titulo', 'resumo', 'conteudo', 'tags')
    list_editable = ('destaque', 'ativo')
    prepopulated_fields = {'slug': ('versao', 'titulo')}
    ordering = ('-data_publicacao',)
