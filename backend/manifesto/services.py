from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

channel_layer = get_channel_layer()

def enviar_painel(manifesto):
    total = manifesto.notas_fiscais.count()

    baixadas = manifesto.notas_fiscais.filter(
        status__in=['BAIXADA', 'OCORRENCIA']
    ).count()

    porcentagem = int((baixadas / total) * 100) if total else 0
    total_notas = total

    remover = manifesto.status != 'EM_TRANSPORTE'
    print("WS ENVIANDO -> TOTAL:", total, "BAIXADAS:", baixadas)

    from django.utils.timezone import localtime
    
    # Converte o horário do banco (UTC) para o fuso horário configurado no Django (ex: America/Sao_Paulo)
    data_registro_local = localtime(manifesto.data_criacao)
    data_registro = data_registro_local.strftime('%d/%m/%Y %H:%M')
    
    from django.utils.text import slugify
    
    # Define o grupo da filial usando o slug do nome (trata caracteres como acentos/espaços)
    nome_filial = manifesto.filial.nome if manifesto.filial else "todas"
    grupo_filial = f"painel_monitoramento_{slugify(nome_filial)}"
    
    payload = {
        "type": "atualizar_painel",
        "data": {
            "manifesto_id": str(manifesto.numero_manifesto),
            "baixadas": baixadas,
            "porcentagem": porcentagem,
            "motorista_nome": manifesto.motorista.nome_completo if manifesto.motorista else "Desconhecido",
            "motorista_categoria": manifesto.motorista.categoria if (manifesto.motorista and manifesto.motorista.categoria) else "EMPRESA",
            "motorista_categoria_display": manifesto.motorista.get_categoria_display() if (manifesto.motorista and hasattr(manifesto.motorista, 'get_categoria_display')) else "Empresa",
            "foto_motorista": manifesto.motorista.foto_perfil.url if (manifesto.motorista and manifesto.motorista.foto_perfil) else None,
            "icone_dispositivo": manifesto.motorista.icone_dispositivo_html if manifesto.motorista else "",
            "remover": remover,
            "total": total_notas, 
            "data_registro": data_registro,
            "data_criacao_iso": manifesto.data_criacao.isoformat() if manifesto.data_criacao else None,
            "ultimo_acesso_iso": localtime(manifesto.ultimo_acesso).isoformat() if manifesto.ultimo_acesso else None,
            "is_antigo": getattr(manifesto, 'is_antigo', False),
            "dias_criado": getattr(manifesto, 'dias_criado', 0)
        }
    }
    
    # Envia para a filial específica
    async_to_sync(channel_layer.group_send)(
        grupo_filial,
        payload
    )
    
    # Se não for "todas", envia também para o painel geral
    if grupo_filial != "painel_monitoramento_todas":
        async_to_sync(channel_layer.group_send)(
            "painel_monitoramento_todas",
            payload
        )

    # ⚡ Transmite em tempo real para o SAC Live também!
    try:
        notificar_atualizacao_cargas_fretes(manifesto.filial if manifesto else None)
    except Exception as sac_err:
        print(f"❌ Erro ao notificar SAC no enviar_painel: {sac_err}")


def notificar_atualizacao_cargas_fretes(filial=None):
    """
    Transmite um evento WebSocket para atualizar em tempo real o painel Cargas / Fretes (SAC).
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    from django.utils.text import slugify
    from django.utils import timezone

    clayer = get_channel_layer()
    if not clayer:
        return

    filial_id_str = str(filial.id) if (filial and hasattr(filial, 'id') and filial.id) else "todas"
    nome_filial_slug = slugify(str(filial.nome)) if (filial and hasattr(filial, 'nome') and filial.nome) else "todas"

    payload = {
        "type": "atualizar_cargas",
        "data": {
            "timestamp": timezone.now().isoformat(),
            "filial_id": filial_id_str
        }
    }

    # Transmite para todas as variações de grupo possíveis para garantir recepção 100% ao vivo
    grupos = set([
        "painel_cargas_fretes_todas",
        f"painel_cargas_fretes_{filial_id_str}",
        f"painel_cargas_fretes_{nome_filial_slug}",
        "painel_monitoramento_todas",
        f"painel_monitoramento_{filial_id_str}"
    ])

    for g in grupos:
        try:
            async_to_sync(clayer.group_send)(g, payload)
        except Exception as e:
            print(f"❌ Erro ao transmitir WS cargas/fretes ({g}): {e}")
