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
