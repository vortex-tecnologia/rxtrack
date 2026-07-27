# backend/common/fcm_service.py
"""
Serviço centralizado para envio de Notificações Push via Firebase Cloud Messaging (FCM)
exclusivamente para motoristas que utilizam o app nativo Android (APK).
"""

import logging
import os
from django.conf import settings
from django.utils import timezone
from usuarios.models import Motorista, NotificacaoPushLog

logger = logging.getLogger(__name__)

# Tenta importar a SDK oficial do Firebase Admin
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("SDK 'firebase-admin' não instalada no ambiente Python.")

_firebase_app_initialized = False

def inicializar_firebase():
    """
    Inicializa a SDK do Firebase Admin se ainda não estiver inicializada.
    Busca o arquivo de chave JSON nas configurações do Django ou no caminho padrão.
    """
    global _firebase_app_initialized
    if not FIREBASE_AVAILABLE:
        return False, "SDK firebase-admin não instalada"

    if _firebase_app_initialized or len(firebase_admin._apps) > 0:
        _firebase_app_initialized = True
        return True, "Firebase já inicializado"

    # Procura pelo arquivo de credenciais do Firebase (serviceAccountKey.json)
    cred_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
    if not cred_path:
        base_dir = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cred_path = os.path.join(base_dir, 'firebase-credentials.json')

    if not os.path.exists(cred_path):
        env_cred = os.getenv('FIREBASE_CREDENTIALS_PATH')
        if env_cred and os.path.exists(env_cred):
            cred_path = env_cred

    if not os.path.exists(cred_path):
        msg = f"Arquivo de credenciais do Firebase não encontrado em: {cred_path}"
        logger.warning(msg)
        return False, msg

    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _firebase_app_initialized = True
        logger.info("🔥 Firebase Admin SDK inicializado com sucesso!")
        return True, "Firebase inicializado"
    except Exception as e:
        msg = f"Erro ao inicializar Firebase Admin SDK: {e}"
        logger.error(msg)
        return False, msg


def enviar_notificacao_push(motorista, titulo, mensagem, tipo='SISTEMA', dados_payload=None):
    """
    Envia uma notificação push via Firebase FCM para um motorista específico (APK).
    
    :param motorista: Instância de Motorista
    :param titulo: Título da notificação
    :param mensagem: Corpo da mensagem
    :param tipo: Categoria ('SISTEMA', 'LEMBRETE', 'MANIFESTO', 'ALERTA', 'MANUAL')
    :param dados_payload: Dicionário opcional com dados customizados (ex: {'manifesto_id': '123'})
    :return: (sucesso: bool, message_id_ou_erro: str)
    """
    if not motorista:
        return False, "Motorista não informado"

    # Regra Fundamental: apenas quem é do APK possui fcm_token cadastrado
    if not motorista.fcm_token:
        msg_erro = f"Motorista {motorista.nome_completo} não possui FCM Token registrado (Usuário PWA ou app antigo)."
        logger.info(msg_erro)
        return False, msg_erro

    # Converte dados extras para string caso haja payload
    payload_clean = {}
    if dados_payload and isinstance(dados_payload, dict):
        for k, v in dados_payload.items():
            payload_clean[str(k)] = str(v) if v is not None else ""

    # Tenta inicializar o Firebase
    sucesso_init, msg_init = inicializar_firebase()
    if not sucesso_init:
        # Registra log de falha por falta de configuração do Firebase
        NotificacaoPushLog.objects.create(
            motorista=motorista,
            titulo=titulo,
            mensagem=mensagem,
            tipo=tipo,
            dados_payload=payload_clean,
            sucesso=False,
            erro_detalhes=f"Configuração do Firebase indisponível: {msg_init}"
        )
        return False, msg_init

    try:
        # Monta a mensagem Firebase FCM Push
        message = messaging.Message(
            notification=messaging.Notification(
                title=titulo,
                body=mensagem,
            ),
            data=payload_clean if payload_clean else None,
            token=motorista.fcm_token.strip(),
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    click_action='FLUTTER_NOTIFICATION_CLICK'
                )
            )
        )

        # Envia a notificação via SDK
        response_id = messaging.send(message)
        logger.info(f"📲 Push enviado para {motorista.nome_completo}! ID: {response_id}")

        # Grava log de sucesso no banco de dados
        NotificacaoPushLog.objects.create(
            motorista=motorista,
            titulo=titulo,
            mensagem=mensagem,
            tipo=tipo,
            dados_payload=payload_clean,
            sucesso=True,
            response_message_id=str(response_id)
        )
        return True, str(response_id)

    except Exception as e:
        erro_msg = str(e)
        logger.error(f"❌ Erro ao enviar FCM Push para {motorista.nome_completo}: {erro_msg}")
        
        # Grava log de erro no banco de dados
        NotificacaoPushLog.objects.create(
            motorista=motorista,
            titulo=titulo,
            mensagem=mensagem,
            tipo=tipo,
            dados_payload=payload_clean,
            sucesso=False,
            erro_detalhes=erro_msg
        )

        # Se o token estiver expirado ou inválido no Firebase, limpa o token do motorista
        if 'Unregistered' in erro_msg or 'invalid-registration-token' in erro_msg.lower():
            logger.warning(f"Token FCM do motorista {motorista.nome_completo} é inválido/expirado. Removendo.")
            motorista.fcm_token = None
            motorista.save(update_fields=['fcm_token'])

        return False, erro_msg


def enviar_notificacao_massa(motoristas_qs_ou_lista, titulo, mensagem, tipo='SISTEMA', dados_payload=None):
    """
    Envia notificação push para múltiplos motoristas com fcm_token cadastrado.
    
    :return: Dicionário com estatísticas do envio
    """
    # Filtra apenas motoristas com token FCM válido
    if hasattr(motoristas_qs_ou_lista, 'filter'):
        candidatos = motoristas_qs_ou_lista.filter(fcm_token__isnull=False).exclude(fcm_token='')
    else:
        candidatos = [m for m in motoristas_qs_ou_lista if m and getattr(m, 'fcm_token', None)]

    stats = {
        'total_candidatos': len(candidatos),
        'sucessos': 0,
        'falhas': 0,
        'detalhes': []
    }

    for m in candidatos:
        ok, res = enviar_notificacao_push(m, titulo, mensagem, tipo=tipo, dados_payload=dados_payload)
        if ok:
            stats['sucessos'] += 1
        else:
            stats['falhas'] += 1
        stats['detalhes'].append({'motorista_id': m.id, 'nome': m.nome_completo, 'sucesso': ok, 'resultado': res})

    return stats


def enviar_notificacao_topico(topico, titulo, mensagem, tipo='SISTEMA', dados_payload=None):
    """
    Envia notificação push para um tópico específico do Firebase FCM (ex: 'todos_motoristas').
    """
    sucesso_init, msg_init = inicializar_firebase()
    if not sucesso_init:
        return False, msg_init

    payload_clean = {str(k): str(v) for k, v in (dados_payload or {}).items()}

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=titulo,
                body=mensagem,
            ),
            data=payload_clean if payload_clean else None,
            topic=topico,
        )
        response_id = messaging.send(message)
        logger.info(f"📲 Push de tópico [{topico}] enviado! ID: {response_id}")
        return True, str(response_id)
    except Exception as e:
        logger.error(f"❌ Erro ao enviar Push de tópico [{topico}]: {e}")
        return False, str(e)
