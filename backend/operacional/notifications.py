# operacional/notifications.py
# API de notificações de erros para o centro de notificações global

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.timezone import localtime
from manifesto.models import LogBaixaNfe
from usuarios.models import Motorista


@login_required
def api_notificacoes_erros(request):
    """
    GET: Retorna erros não lidos para o dropdown de notificações.
    Filtra por filial do usuário logado.
    """
    try:
        perfil = Motorista.objects.get(user=request.user)
        filial = perfil.filial
    except Motorista.DoesNotExist:
        return JsonResponse({'count': 0, 'notificacoes': []})

    # Busca apenas logs de ERRO não lidos (da filial do usuário ou sem filial)
    from operacional.models import LogErroOperacional
    erros_qs = LogBaixaNfe.objects.filter(
        tipo__icontains='ERRO',
        lido=False,
    )
    
    if filial:
        from django.db.models import Q
        erros_qs = erros_qs.filter(Q(filial=filial) | Q(filial__isnull=True))

    total_nao_lidos = erros_qs.count()

    # Retorna as últimas 20 para o dropdown
    ultimos_erros = erros_qs.order_by('-criado_em')[:20]

    notificacoes = []
    for log in ultimos_erros:
        notificacoes.append({
            'id': log.id,
            'titulo': f"Erro na Nota Fiscal {log.numero_nota} - #{log.manifesto_numero}",
            'mensagem': log.mensagem[:150] if log.mensagem else "Erro retornado da ESL",
            'tipo': log.tipo,
            'hora': localtime(log.criado_em).strftime('%d/%m %H:%M'),
            'numero_nota': log.numero_nota,
            'manifesto_numero': log.manifesto_numero,
        })

    # Conta os erros operacionais pendentes na Torre de Erros para pulsar o botão
    erros_op_qs = LogErroOperacional.objects.filter(resolvido=False)
    if filial:
        erros_op_qs = erros_op_qs.filter(Q(filial=filial) | Q(filial__isnull=True))
    pendentes_torre = erros_op_qs.count()

    return JsonResponse({
        'count': total_nao_lidos,
        'notificacoes': notificacoes,
        'erros_pendentes_torre': pendentes_torre,
    })


@login_required
def api_marcar_notificacoes_lidas(request):
    """
    POST: Marca todas as notificações de erro como lidas.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método não permitido'}, status=405)

    try:
        perfil = Motorista.objects.get(user=request.user)
        filial = perfil.filial
    except Motorista.DoesNotExist:
        return JsonResponse({'success': True})

    erros_qs = LogBaixaNfe.objects.filter(
        tipo__icontains='ERRO',
        lido=False,
    )
    
    if filial:
        from django.db.models import Q
        erros_qs = erros_qs.filter(Q(filial=filial) | Q(filial__isnull=True))

    erros_qs.update(lido=True)

    return JsonResponse({'success': True})


@login_required
def api_marcar_notificacao_lida(request, notif_id):
    """
    POST: Marca uma notificação de erro específica como lida.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Método não permitido'}, status=405)
    
    LogBaixaNfe.objects.filter(id=notif_id).update(lido=True)
    return JsonResponse({'success': True})


@login_required
def api_logs_baixa_nfe(request):
    """
    GET: Retorna todos os logs de baixa de NF-e para o modal de histórico completo.
    """
    try:
        perfil = Motorista.objects.get(user=request.user)
        filial = perfil.filial
    except Motorista.DoesNotExist:
        return JsonResponse([], safe=False)

    logs_qs = LogBaixaNfe.objects.all()

    if filial:
        from django.db.models import Q
        logs_qs = logs_qs.filter(Q(filial=filial) | Q(filial__isnull=True))

    logs = logs_qs.order_by('-criado_em')[:100]

    resultado = []
    for log in logs:
        resultado.append({
            'data': localtime(log.criado_em).strftime('%d/%m %H:%M'),
            'numero_nota': log.numero_nota,
            'manifesto_numero': log.manifesto_numero,
            'tipo': log.get_tipo_display(),
            'tipo_raw': log.tipo,
            'mensagem': log.mensagem or '-',
            'is_erro': log.is_erro,
        })

    return JsonResponse(resultado, safe=False)
