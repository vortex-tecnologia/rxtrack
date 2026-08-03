# backend/common/tasks_notificacoes.py
"""
Tarefas e rotinas automatizadas para disparo de Notificações Push (Firebase FCM)
para os motoristas do APK durante o dia.
"""

import logging
from django.utils import timezone
from usuarios.models import Motorista
from common.fcm_service import enviar_notificacao_push, enviar_notificacao_massa

logger = logging.getLogger(__name__)


def enviar_lembrete_gps_diario():
    """
    Envia lembrete de ativação do GPS / App para todos os motoristas do APK.
    Pode ser agendado para rodar às 08:00 e 13:00.
    """
    titulo = "📍 Mantenha o GPS Ativo"
    mensagem = "Olá! Para garantir a atualização das entregas do dia, abra o app RXTrack e verifique se o GPS está ativado."
    
    motoristas_apk = Motorista.objects.filter(fcm_token__isnull=False).exclude(fcm_token='')
    logger.info(f"Disparando lembrete de GPS diário para {motoristas_apk.count()} motorista(s) APK...")
    
    return enviar_notificacao_massa(
        motoristas_qs_ou_lista=motoristas_apk,
        titulo=titulo,
        mensagem=mensagem,
        tipo='LEMBRETE'
    )


def notificar_atribuicao_manifesto(motorista, numero_manifesto, total_notas=None):
    """
    Notifica o motorista (APK) quando um novo manifesto for atribuído a ele no TMS.
    """
    if not motorista or not motorista.fcm_token:
        return False, "Motorista sem FCM token"

    titulo = f"🚛 Novo Manifesto {numero_manifesto}"
    mensagem = f"Um novo manifesto (#{numero_manifesto}) foi atribuído a você."
    if total_notas:
        mensagem += f" Total de entregas: {total_notas} notas."

    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='MANIFESTO',
        dados_payload={'manifesto': str(numero_manifesto), 'acao': 'ABRIR_MANIFESTO'}
    )


def notificar_alerta_motorista(motorista, titulo, mensagem, dados_extras=None):
    """
    Envia um alerta operacional individual para a tela do celular do motorista.
    """
    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='ALERTA',
        dados_payload=dados_extras
    )


def varrer_e_notificar_manifestos_ativos():
    """
    Varre todos os manifestos ativos ('EM_TRANSPORTE' ou 'AGUARDANDO') no sistema
    e envia uma notificação push para os motoristas vinculados que utilizam o APK.
    """
    from manifesto.models import Manifesto

    manifestos_ativos = Manifesto.objects.filter(
        status__in=['EM_TRANSPORTE', 'AGUARDANDO'],
        motorista__fcm_token__isnull=False
    ).exclude(motorista__fcm_token='').select_related('motorista')

    count = 0
    motoristas_notificados = set()

    for mft in manifestos_ativos:
        motorista = mft.motorista
        if not motorista or motorista.id in motoristas_notificados:
            continue

        titulo = f"🚛 Viagem em Andamento (#{mft.numero_manifesto})"
        mensagem = f"Olá {motorista.nome_completo.split()[0]}! Seu manifesto #{mft.numero_manifesto} está ativo. Mantenha o aplicativo aberto e o GPS ligado."
        
        ok, _ = enviar_notificacao_push(
            motorista=motorista,
            titulo=titulo,
            mensagem=mensagem,
            tipo='LEMBRETE',
            dados_payload={'manifesto': str(mft.numero_manifesto), 'status': mft.status}
        )
        if ok:
            count += 1
            motoristas_notificados.add(motorista.id)

    logger.info(f"🔎 Varredura de manifestos ativos: {count} motorista(s) notificado(s) via Push FCM.")
    return count


def notificar_mensagem_sac(ticket, atendente_nome=None):
    """
    Notifica o motorista quando um agente do SAC responde ou envia mensagem no chamado.
    Verifica quantas mensagens NÃO LIDAS do SAC existem no ticket para formatar o texto.
    """
    motorista = getattr(ticket, 'motorista', None)
    if not motorista or not motorista.fcm_token:
        return False, "Motorista sem FCM token"

    # Conta mensagens não lidas enviadas pelo SAC
    nao_lidas = ticket.mensagens.filter(enviado_por_motorista=False, lida=False).count()
    
    nome_atendente = atendente_nome or "SAC"
    if nao_lidas > 1:
        mensagem = f"Você tem {nao_lidas} mensagens para ler de {nome_atendente}."
    else:
        mensagem = f"Você tem uma nova mensagem de {nome_atendente}."

    titulo = "💬 Nova Mensagem do SAC"

    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='CHAT_SAC',
        dados_payload={
            'ticket_id': str(ticket.id),
            'acao': 'ABRIR_CHAT',
            'nao_lidas': str(nao_lidas)
        }
    )


def notificar_item_adicionado_manifesto(motorista, manifesto_num, item_num, tipo_item='NOTA'):
    """
    Notifica o motorista quando um novo item (nota ou coleta) for adicionado ao seu manifesto.
    """
    if not motorista or not motorista.fcm_token:
        return False, "Motorista sem FCM token"

    tipo_str = "Coleta" if tipo_item == 'COLETA' else "Nota Fiscal"
    titulo = f"➕ Item Adicionado (MFT #{manifesto_num})"
    mensagem = f"A {tipo_str} nº {item_num} foi adicionada ao seu manifesto #{manifesto_num}. Acesse o aplicativo para visualizar a lista atualizada."

    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='MANIFESTO_UPDATE',
        dados_payload={
            'manifesto': str(manifesto_num),
            'item_numero': str(item_num),
            'acao': 'RECARREGAR_ITENS'
        }
    )


def notificar_item_removido_manifesto(motorista, manifesto_num, item_num, tipo_item='NOTA'):
    """
    Notifica o motorista quando um item (nota ou coleta) for removido do seu manifesto.
    """
    if not motorista or not motorista.fcm_token:
        return False, "Motorista sem FCM token"

    tipo_str = "Coleta" if tipo_item == 'COLETA' else "Nota Fiscal"
    titulo = f"➖ Item Removido (MFT #{manifesto_num})"
    mensagem = f"A {tipo_str} nº {item_num} foi removida do seu manifesto #{manifesto_num}. Acesse o aplicativo para visualizar a lista atualizada."

    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='MANIFESTO_UPDATE',
        dados_payload={
            'manifesto': str(manifesto_num),
            'item_numero': str(item_num),
            'acao': 'RECARREGAR_ITENS'
        }
    )


def notificar_manifesto_removido(motorista, manifesto_num):
    """
    Notifica o motorista quando o seu manifesto inteiro for cancelado ou deletado.
    """
    if not motorista or not motorista.fcm_token:
        return False, "Motorista sem FCM token"

    titulo = f"🚨 Manifesto Removido (#{manifesto_num})"
    mensagem = f"Seu manifesto #{manifesto_num} foi cancelado/removido pela operação."

    return enviar_notificacao_push(
        motorista=motorista,
        titulo=titulo,
        mensagem=mensagem,
        tipo='MANIFESTO_CANCELADO',
        dados_payload={
            'manifesto': str(manifesto_num),
            'acao': 'MANIFESTO_REMOVIDO'
        }
    )


