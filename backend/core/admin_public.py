# core/admin_public.py
# Admin Site exclusivo para o Painel Global (Schema Public)
# Só mostra os models que existem no banco público: Tenants + Auth + Tutoriais

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin, GroupAdmin

from tenants.models import Client, Domain
from tutoriais.models import VideoTreinamento
from blog.models import PostBlog, AlertaSistema


class PublicAdminSite(AdminSite):
    site_header = "RXTrack — Painel Global"
    site_title = "RXTrack Admin Global"
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


# --- Alertas do Sistema (Comunicados por TMS / Schemas) ---
from django.utils.html import format_html

class PublicAlertaSistemaAdmin(admin.ModelAdmin):
    list_display = ('titulo_badge', 'tms_alvo_badge', 'schemas_especificos', 'data_criacao', 'fixar_topo', 'ativo')
    list_filter = ('tipo', 'tms_alvo', 'ativo', 'fixar_topo', 'data_criacao')
    search_fields = ('titulo', 'conteudo_html', 'schemas_especificos')
    list_editable = ('ativo', 'fixar_topo')
    ordering = ('-fixar_topo', '-data_criacao')
    fieldsets = (
        ("Identificação do Alerta", {
            "fields": ("titulo", "tipo", "ativo", "fixar_topo")
        }),
        ("Filtros de Destinatários (Sistemas e Clientes)", {
            "fields": ("tms_alvo", "schemas_especificos"),
            "description": "Selecione qual provedor TMS receberá o aviso (ex: ESL Cloud, Brudam ou Todos). Se desejar restringir apenas a certos clientes, liste os schemas separados por vírgula."
        }),
        ("Conteúdo do Alerta (HTML Permitido)", {
            "fields": ("conteudo_html",),
            "description": "Você pode utilizar tags HTML como <p>, <b>, <ul>, <li>, etc."
        }),
        ("Agendamento / Expiração", {
            "fields": ("data_expiracao",),
            "classes": ("collapse",),
            "description": "Opcional. Se preenchido, o alerta sairá do ar automaticamente após esse horário."
        }),
    )

    def titulo_badge(self, obj):
        cores = {
            'PERIGO': '#ef4444',
            'AVISO': '#f59e0b',
            'INFO': '#3b82f6',
            'SUCESSO': '#10b981'
        }
        cor = cores.get(obj.tipo, '#6b7280')
        return format_html(
            '<span style="display: inline-flex; align-items: center; gap: 6px;">'
            '<span style="width: 10px; height: 10px; border-radius: 50%; background-color: {};"></span>'
            '<strong>{}</strong>'
            '</span>',
            cor, obj.titulo
        )
    titulo_badge.short_description = "Título / Severidade"

    def tms_alvo_badge(self, obj):
        return format_html(
            '<span style="background-color: #0f172a; color: #38bdf8; font-weight: 600; padding: 4px 8px; border-radius: 6px; font-size: 0.8rem;">{}</span>',
            obj.get_tms_alvo_display()
        )
    tms_alvo_badge.short_description = "Provedor Alvo"


public_admin_site.register(AlertaSistema, PublicAlertaSistemaAdmin)

