def configuracao_global(request):
    from configuracao.utils import get_config
    try:
        return {'config_sistema': get_config()}
    except Exception:
        return {'config_sistema': None}
