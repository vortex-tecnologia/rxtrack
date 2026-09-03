# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# financeiro/templatetags/financeiro_tags.py

from django import template

register = template.Library()


@register.filter(name='dict_lookup')
def dict_lookup(dictionary, key):
    """
    Permite lookup de chaves em dicionários dentro dos templates Django.
    Ex: {{ meu_dict|dict_lookup:chave }}
    """
    if not dictionary:
        return None
    if isinstance(dictionary, dict):
        res = dictionary.get(key)
        if res is not None:
            return res
        try:
            return dictionary.get(str(key))
        except (ValueError, TypeError):
            pass
        try:
            return dictionary.get(int(key))
        except (ValueError, TypeError):
            pass
    return None


@register.filter(name='format_input_decimal')
def format_input_decimal(value, default="0.00"):
    """
    Formata valores decimais com ponto (sempre padrão numérico) para uso seguro em inputs HTML.
    Evita que o navegador limpe o campo por causa de vírgula de localização (pt-br).
    """
    if value is None or value == "":
        return default
    try:
        val = float(str(value).replace(',', '.'))
        return f"{val:.2f}"
    except (ValueError, TypeError):
        return default
