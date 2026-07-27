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
