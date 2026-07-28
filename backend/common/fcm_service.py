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

    # Procura pelo arquivo de credenciais do Firebase (*firebase*.json ou firebase-credentials.json)
    cred_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
    if not cred_path or not os.path.exists(cred_path):
        import glob
        base_dir = getattr(settings, 'BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        possible_paths = [
            os.path.join(base_dir, 'firebase-credentials.json'),
            os.path.join(base_dir, 'firebase-adminsdk.json'),
        ]
        possible_paths.extend(glob.glob(os.path.join(base_dir, '*firebase*.json')))
        possible_paths.extend(glob.glob(os.path.join(os.path.dirname(base_dir), '*firebase*.json')))
        
        env_cred = os.getenv('FIREBASE_CREDENTIALS_PATH')
        if env_cred:
            possible_paths.insert(0, env_cred)

        cred_path = None
        for p in possible_paths:
            if p and os.path.exists(p):
                cred_path = p
                break

    if not cred_path or not os.path.exists(cred_path):
        msg = f"Arquivo de credenciais do Firebase (*firebase*.json) não encontrado no diretório do projeto."
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
                    sound='rxtrack_notification',
                    default_sound=False,
                    default_vibrate_timings=True,
                    channel_id='rxtrack_push_channel'
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

    except messaging.UnregisteredError as unreg_err:
        msg_caducou = f"Token FCM do motorista {motorista.nome_completo} caducou/expirou (app foi reinstalado). Removendo token antigo do banco."
        logger.warning(f"⚠️ {msg_caducou}")

        # Limpa o token antigo expirado para aguardar novo login do motorista no APK
        motorista.fcm_token = None
        motorista.save(update_fields=['fcm_token'])

        NotificacaoPushLog.objects.create(
            motorista=motorista,
            titulo=titulo,
            mensagem=mensagem,
            tipo=tipo,
            dados_payload=payload_clean,
            sucesso=False,
            erro_detalhes=f"NotRegistered - Token removido do banco: {unreg_err}"
        )
        return False, "NotRegistered - Token removido do banco (Aguardando novo login no app)"

    except Exception as e:
        erro_msg = str(e)
        logger.error(f"❌ Erro ao enviar FCM Push para {motorista.nome_completo}: {erro_msg}")
        
        # Se o token estiver expirado ou inválido no Firebase, limpa o token do motorista
        if 'Unregistered' in erro_msg or 'invalid-registration-token' in erro_msg.lower() or 'notregistered' in erro_msg.lower():
            logger.warning(f"Token FCM do motorista {motorista.nome_completo} é inválido/expirado ({erro_msg}). Removendo do banco.")
            motorista.fcm_token = None
            motorista.save(update_fields=['fcm_token'])

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
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='rxtrack_notification',
                    default_sound=False,
                    default_vibrate_timings=True,
                    channel_id='rxtrack_push_channel'
                )
            )
        )

        response_id = messaging.send(message)
        logger.info(f"📲 Push de tópico [{topico}] enviado! ID: {response_id}")
        return True, str(response_id)
    except Exception as e:
        logger.error(f"❌ Erro ao enviar Push de tópico [{topico}]: {e}")
        return False, str(e)
