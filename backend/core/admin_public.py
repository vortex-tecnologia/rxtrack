# core/admin_public.py
# Admin Site exclusivo para o Painel Global (Schema Public)
# Só mostra os models que existem no banco público: Tenants + Auth + Tutoriais

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin

from tenants.models import Client, Domain
from tutoriais.models import VideoTreinamento
from blog.models import PostBlog


class PublicAdminSite(AdminSite):
    site_header = "QuickTrack — Painel Global"
    site_title = "QuickTrack Admin Global"
    index_title = "Gestão de Clientes e Plataforma"


public_admin_site = PublicAdminSite(name='public_admin')


# ══════════════════════════════════════════════════════
#  Registrar apenas os models que existem no public
# ══════════════════════════════════════════════════════

# --- Auth (Usuários e Grupos do painel global) ---
public_admin_site.register(User, UserAdmin)
public_admin_site.register(Group, GroupAdmin)


# --- Tenants (Clientes e Domínios) ---
class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


class PublicClientAdmin(admin.ModelAdmin):
    list_display = ('schema_name', 'name', 'created_on')
    search_fields = ('schema_name', 'name')
    inlines = [DomainInline]


class PublicDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain', 'tenant__name')


public_admin_site.register(Client, PublicClientAdmin)
public_admin_site.register(Domain, PublicDomainAdmin)


# --- Tutoriais (Vídeos de treinamento compartilhados) ---
class PublicVideoTreinamentoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'url_youtube', 'visualizacoes', 'likes', 'dislikes', 'ativo', 'created_at')
    list_filter = ('ativo', 'created_at')
    search_fields = ('titulo', 'descricao')


public_admin_site.register(VideoTreinamento, PublicVideoTreinamentoAdmin)


# --- Blog & Lançamentos (Compartilhados com todos os clientes) ---
class PublicPostBlogAdmin(admin.ModelAdmin):
    list_display = ('versao', 'titulo', 'categoria', 'autor', 'data_publicacao', 'destaque', 'ativo', 'visualizacoes')
    list_filter = ('categoria', 'ativo', 'destaque', 'data_publicacao')
    search_fields = ('versao', 'titulo', 'resumo', 'conteudo', 'tags')
    list_editable = ('destaque', 'ativo')
    prepopulated_fields = {'slug': ('versao', 'titulo')}


public_admin_site.register(PostBlog, PublicPostBlogAdmin)
