from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Client, Domain

class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1

@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ('schema_name', 'name', 'created_on')
    search_fields = ('schema_name', 'name')
    inlines = [DomainInline]

@admin.register(Domain)
class DomainAdmin(ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain', 'tenant__name')
