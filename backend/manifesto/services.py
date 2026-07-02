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
            "foto_motorista": manifesto.motorista.foto_perfil.url if (manifesto.motorista and manifesto.motorista.foto_perfil) else None,
            "remover": remover,
            "total": total_notas, 
            "data_registro": data_registro
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
