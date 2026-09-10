def configuracao_global(request):
    from configuracao.utils import get_config
    contexto = {
        'config_sistema': None,
        'alertas_sistema_ativos': [],
        'alerta_sistema_principal': None,
    }
    try:
        config = get_config()
        contexto['config_sistema'] = config

        # Busca alertas globais da plataforma (SHARED_APP blog.AlertaSistema)
        from django.db import connection, models
        from django.utils import timezone

        schema_atual = getattr(connection, 'schema_name', 'public')
        tms_atual = getattr(config, 'tms_provider', 'esl_cloud') if config else 'esl_cloud'

        from blog.models import AlertaSistema
        agora = timezone.now()
        qs = AlertaSistema.objects.filter(ativo=True)
        qs = qs.filter(models.Q(data_expiracao__isnull=True) | models.Q(data_expiracao__gt=agora))

        alertas_filtrados = []
        for alerta in qs.order_by('-fixar_topo', '-data_criacao'):
            # 1. Filtro de Provedor TMS
            if alerta.tms_alvo != 'TODOS' and alerta.tms_alvo != tms_atual:
                continue

            # 2. Filtro de Schemas específicos (opcional)
            if alerta.schemas_especificos:
                schemas_permitidos = [s.strip().lower() for s in alerta.schemas_especificos.split(',') if s.strip()]
                if schema_atual.lower() not in schemas_permitidos:
                    continue

            alertas_filtrados.append(alerta)

        contexto['alertas_sistema_ativos'] = alertas_filtrados
        contexto['alerta_sistema_principal'] = alertas_filtrados[0] if alertas_filtrados else None

    except Exception:
        pass

    return contexto

