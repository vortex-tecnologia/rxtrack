import re
from django.core.cache import cache
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils.timezone import localtime

def classificar_erro(mensagem_erro):
    """
    Percorre as RegraClassificacaoErro por prioridade e retorna a primeira que bater.
    Usa cache de 5 min para evitar queries repetidas.
    Retorna (severidade, publico_alvo, exibir_torre, regra) ou defaults.
    """
    if not mensagem_erro:
        return None, 'AMBOS', True, None

    regras = cache.get('regras_classificacao_erro')
    if regras is None:
        from operacional.models import RegraClassificacaoErro
        regras = list(RegraClassificacaoErro.objects.filter(ativo=True).order_by('prioridade'))
        cache.set('regras_classificacao_erro', regras, 300)
    
    msg_lower = str(mensagem_erro).lower()
    
    for regra in regras:
        if regra.usar_regex:
            if re.search(regra.pattern, str(mensagem_erro), re.IGNORECASE):
                return regra.severidade, regra.publico_alvo, regra.exibir_torre, regra
        else:
            if regra.pattern.lower() in msg_lower:
                return regra.severidade, regra.publico_alvo, regra.exibir_torre, regra
    
    # Nenhuma regra bateu → usa defaults
    return None, 'AMBOS', True, None


def registrar_erro_torre(filial, categoria, severidade_padrao, titulo, descricao,
                          erro_raw="", manifesto_numero=None, nota_fiscal_numero=None,
                          motorista_nome=None):
    """
    Registra um erro na Torre de Controle e notifica via WebSocket.
    Se o mesmo erro já existir em ABERTO para a mesma NF/Manifesto, incrementa a contagem de tentativas.
    """
    from configuracao.utils import get_config
    from django.utils import timezone
    from operacional.models import LogErroOperacional

    config = get_config()
    if not getattr(config, 'modulo_torre_erros', False):
        return None
    
    # Classifica o erro pelo texto
    sev_regra, publico, exibir, regra = classificar_erro(erro_raw or descricao)
    severidade_final = sev_regra or severidade_padrao

    agora = timezone.now()
    agora_iso = agora.isoformat()

    # 📌 Busca se já existe erro IDÊNTICO em ABERTO
    qs_existente = LogErroOperacional.objects.filter(
        filial=filial,
        status='ABERTO',
        categoria=categoria
    )

    if manifesto_numero:
        qs_existente = qs_existente.filter(manifesto_numero=manifesto_numero)
    if nota_fiscal_numero:
        qs_existente = qs_existente.filter(nota_fiscal_numero=nota_fiscal_numero)

    existente = None
    desc_limpa = (descricao or '').strip()
    raw_limpo = (erro_raw or '').strip()
    tit_limpo = (titulo or '').strip()

    for item in qs_existente:
        if (item.descricao and item.descricao.strip() == desc_limpa) or \
           (item.erro_raw and item.erro_raw.strip() == raw_limpo) or \
           (item.titulo and item.titulo.strip() == tit_limpo):
            existente = item
            break

    if existente:
        # 📌 Erro repetido: Incrementa contador e armazena histórico da tentativa
        existente.qtd_tentativas = (existente.qtd_tentativas or 1) + 1
        
        hist = existente.historico_tentativas or []
        if not hist and existente.criado_em:
            hist = [timezone.localtime(existente.criado_em).isoformat()]
        hist.append(agora_iso)
        existente.historico_tentativas = hist

        existente.severidade = severidade_final
        if motorista_nome and not existente.motorista_nome:
            existente.motorista_nome = motorista_nome
            
        existente.save()

        if exibir:
            enviar_erro_torre_ws(existente, evento="atualizacao_erro")

        return existente
    else:
        # 📌 Novo Erro
        erro = LogErroOperacional.objects.create(
            filial=filial,
            categoria=categoria,
            severidade=severidade_final,
            publico_alvo=publico,
            titulo=titulo,
            descricao=descricao,
            erro_raw=erro_raw,
            manifesto_numero=manifesto_numero,
            nota_fiscal_numero=nota_fiscal_numero,
            motorista_nome=motorista_nome,
            regra_aplicada=regra,
            qtd_tentativas=1,
            historico_tentativas=[agora_iso]
        )
        
        if exibir:
            enviar_erro_torre_ws(erro, evento="novo_erro")
        
        return erro


def enviar_erro_torre_ws(erro, evento="novo_erro"):
    """Envia o erro para os grupos WebSocket corretos."""
    from datetime import datetime
    from django.utils import timezone

    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    hist_formatado = []
    if getattr(erro, 'historico_tentativas', None):
        for h in erro.historico_tentativas:
            try:
                dt = datetime.fromisoformat(h)
                hist_formatado.append(timezone.localtime(dt).strftime('%d/%m/%Y %H:%M:%S'))
            except Exception:
                hist_formatado.append(str(h))

    payload = {
        "type": evento,
        "data": {
            "id": erro.id,
            "severidade": erro.severidade,
            "categoria": erro.categoria,
            "categoria_display": erro.get_categoria_display(),
            "titulo": erro.titulo,
            "descricao": erro.descricao[:300],
            "manifesto_numero": erro.manifesto_numero,
            "nota_fiscal_numero": erro.nota_fiscal_numero,
            "motorista_nome": erro.motorista_nome,
            "criado_em": localtime(erro.criado_em).isoformat(),
            "atualizado_em": localtime(erro.atualizado_em).isoformat() if erro.atualizado_em else None,
            "qtd_tentativas": getattr(erro, 'qtd_tentativas', 1),
            "historico_tentativas": hist_formatado,
            "publico_alvo": erro.publico_alvo,
        }
    }
    
    # Envia para grupo da filial
    grupo_filial = f"torre_erros_{erro.filial_id}"
    async_to_sync(channel_layer.group_send)(grupo_filial, payload)
    
    # Envia também para "todas"
    if grupo_filial != "torre_erros_todas":
        async_to_sync(channel_layer.group_send)("torre_erros_todas", payload)


def resolver_erros_automaticamente(manifesto_numero, nota_fiscal_numero, filial):
    """
    Quando uma tentativa posterior (retry) dá certo, o sistema resolve
    automaticamente os erros anteriores da mesma NF ou Manifesto.
    """
    from operacional.models import LogErroOperacional
    from django.db.models import Q
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from django.utils import timezone
    
    if not manifesto_numero and not nota_fiscal_numero:
        return
        
    qs = LogErroOperacional.objects.filter(status='ABERTO')
    
    if filial:
        qs = qs.filter(Q(filial=filial) | Q(filial__isnull=True))
        
    if manifesto_numero and nota_fiscal_numero:
        qs = qs.filter(manifesto_numero=manifesto_numero, nota_fiscal_numero=nota_fiscal_numero)
    elif manifesto_numero:
        qs = qs.filter(manifesto_numero=manifesto_numero)
    elif nota_fiscal_numero:
        qs = qs.filter(nota_fiscal_numero=nota_fiscal_numero)
        
    erros_para_resolver = list(qs)
    if not erros_para_resolver:
        return
        
    qs.update(
        status='AUTO_RESOLVIDO',
        resolucao_automatica=True,
        data_resolucao=timezone.now(),
        observacao_resolucao="Resolvido automaticamente (retentativa de integração bem sucedida)."
    )
    
    # Notificar via WebSocket
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
        
    for erro in erros_para_resolver:
        payload = {
            "type": "erro_resolvido",
            "data": {
                "id": erro.id,
                "resolvido_por_nome": "Sistema (Automático)",
                "data_resolucao": timezone.localtime(timezone.now()).isoformat()
            }
        }
        
        grupo_filial = f"torre_erros_{erro.filial_id}" if erro.filial_id else "torre_erros_todas"
        async_to_sync(channel_layer.group_send)(grupo_filial, payload)
        
        if grupo_filial != "torre_erros_todas":
            async_to_sync(channel_layer.group_send)("torre_erros_todas", payload)
