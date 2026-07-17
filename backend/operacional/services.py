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
    Retorna None se o módulo estiver desativado.
    """
    # Verifica se módulo está ativo
    from configuracao.utils import get_config
    config = get_config()
    if not getattr(config, 'modulo_torre_erros', False):
        return None
    
    # Classifica o erro pelo texto
    sev_regra, publico, exibir, regra = classificar_erro(erro_raw or descricao)
    severidade_final = sev_regra or severidade_padrao
    
    from operacional.models import LogErroOperacional
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
    )
    
    # Notifica via WebSocket se deve exibir na torre
    if exibir:
        enviar_erro_torre_ws(erro)
    
    return erro


def enviar_erro_torre_ws(erro):
    """Envia o erro para os grupos WebSocket corretos."""
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    
    payload = {
        "type": "novo_erro",
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
            "publico_alvo": erro.publico_alvo,
        }
    }
    
    # Envia para grupo da filial
    grupo_filial = f"torre_erros_{erro.filial_id}"
    async_to_sync(channel_layer.group_send)(grupo_filial, payload)
    
    # Envia também para "todas"
    if grupo_filial != "torre_erros_todas":
        async_to_sync(channel_layer.group_send)("torre_erros_todas", payload)
