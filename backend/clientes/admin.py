# clientes/admin.py
from django import forms
from django.contrib import admin
from .models import UsuarioCliente, VinculoPagador


def get_pagadores_choices_and_docs():
    """
    Retorna a lista de escolhas de pagadores ordenadas e um mapa {nome: documento}.
    Busca os pagadores reais importados na tabela Frete e os cadastrados no Financeiro.
    """
    mapa_docs = {}
    vistos = set()

    # 1. Busca em Fretes (pagadores reais importados nos manifestos)
    try:
        from manifesto.models import Frete
        fretes_qs = Frete.objects.exclude(
            pagador_nome__isnull=True
        ).exclude(
            pagador_nome=''
        ).values('pagador_nome', 'pagador_documento').distinct().order_by('pagador_nome')

        for f in fretes_qs:
            nome = (f.get('pagador_nome') or '').strip()
            doc = (f.get('pagador_documento') or '').strip()
            if nome:
                key = nome.upper()
                if key not in vistos:
                    vistos.add(key)
                    mapa_docs[nome] = doc
                elif doc and not mapa_docs.get(nome):
                    mapa_docs[nome] = doc
    except Exception:
        pass

    # 2. Busca em ClienteBasePagadora (do módulo Financeiro)
    try:
        from financeiro.models import ClienteBasePagadora
        cbp_qs = ClienteBasePagadora.objects.exclude(
            nome__isnull=True
        ).exclude(
            nome=''
        ).values('nome', 'documento').order_by('nome')

        for c in cbp_qs:
            nome = (c.get('nome') or '').strip()
            doc = (c.get('documento') or '').strip()
            if nome:
                key = nome.upper()
                if key not in vistos:
                    vistos.add(key)
                    mapa_docs[nome] = doc
                elif doc and not mapa_docs.get(nome):
                    mapa_docs[nome] = doc
    except Exception:
        pass

    choices = [('', '--------- Selecione um Pagador Cadastrado ---------')]
    nomes_ordenados = sorted(mapa_docs.keys(), key=lambda x: x.upper())
    for nome in nomes_ordenados:
        doc = mapa_docs.get(nome)
        label = f"{nome} ({doc})" if doc else nome
        choices.append((nome, label))

    return choices, mapa_docs


class VinculoPagadorForm(forms.ModelForm):
    class Meta:
        model = VinculoPagador
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices, mapa_docs = get_pagadores_choices_and_docs()

        # Garante que a opção atual salva no registro seja preservada caso não esteja na lista
        val_atual = self.instance.pagador_nome if self.instance and self.instance.pk else None
        if val_atual and not any(c[0] == val_atual for c in choices):
            doc = self.instance.pagador_documento or ''
            label = f"{val_atual} ({doc})" if doc else val_atual
            choices.append((val_atual, label))

        # Se temos pagadores encontrados, renderiza como Select com estilo select2
        if len(choices) > 1:
            self.fields['pagador_nome'] = forms.ChoiceField(
                choices=choices,
                required=True,
                label="Pagador Cadastrado",
                widget=forms.Select(attrs={
                    'class': 'select-pagador-dropdown select2',
                    'style': 'min-width: 320px; max-width: 500px;'
                })
            )
        else:
            self.fields['pagador_nome'].widget = forms.TextInput(attrs={
                'placeholder': 'Digite o nome do pagador...',
                'style': 'min-width: 250px;'
            })

        # Estilo do CNPJ
        if 'pagador_documento' in self.fields:
            self.fields['pagador_documento'].widget.attrs.update({
                'placeholder': 'Auto-preenchido ao selecionar',
                'style': 'min-width: 180px;'
            })

    def clean(self):
        cleaned_data = super().clean()
        pagador_nome = cleaned_data.get('pagador_nome')
        pagador_documento = cleaned_data.get('pagador_documento')

        # Se o CNPJ não foi informado na tela, busca automaticamente no mapa
        if pagador_nome and not pagador_documento:
            _, mapa_docs = get_pagadores_choices_and_docs()
            doc_encontrado = mapa_docs.get(pagador_nome)
            if doc_encontrado:
                cleaned_data['pagador_documento'] = doc_encontrado
                self.instance.pagador_documento = doc_encontrado

        return cleaned_data


class VinculoPagadorInline(admin.TabularInline):
    """Inline para vincular pagadores existentes diretamente na tela do cliente."""
    model = VinculoPagador
    form = VinculoPagadorForm
    extra = 1
    fields = ('pagador_nome', 'pagador_documento', 'ativo')

    class Media:
        js = ('js/admin_pagador.js',)


@admin.register(UsuarioCliente)
class UsuarioClienteAdmin(admin.ModelAdmin):
    list_display = ['nome_completo', 'cpf', 'email', 'ativo', 'criado_em', 'ultimo_acesso']
    list_filter = ['ativo']
    search_fields = ['nome_completo', 'cpf', 'email']
    readonly_fields = ['criado_em', 'ultimo_acesso']
    inlines = [VinculoPagadorInline]

    fieldsets = (
        ('Dados do Cliente', {
            'fields': ('nome_completo', 'cpf', 'email', 'telefone')
        }),
        ('Conta de Acesso', {
            'fields': ('user', 'ativo'),
            'description': 'O auth.User é criado automaticamente no primeiro login do cliente.'
        }),
        ('Informações do Sistema', {
            'fields': ('criado_em', 'ultimo_acesso'),
            'classes': ('collapse',)
        }),
    )

    class Media:
        js = ('js/admin_pagador.js',)


@admin.register(VinculoPagador)
class VinculoPagadorAdmin(admin.ModelAdmin):
    form = VinculoPagadorForm
    list_display = ['usuario_cliente', 'pagador_nome', 'pagador_documento', 'ativo', 'criado_em']
    list_filter = ['ativo']
    search_fields = ['pagador_nome', 'pagador_documento', 'usuario_cliente__nome_completo']
    autocomplete_fields = ['usuario_cliente']

    class Media:
        js = ('js/admin_pagador.js',)

