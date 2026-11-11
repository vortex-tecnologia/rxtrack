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


def _tentar_envio_webpush_pwa(motorista, titulo, mensagem, dados_payload=None):
    """
    Tenta enviar notificação via WebPush (VAPID / Service Worker) para motoristas no PWA.
    Retorna (enviados_count, erro_str).
    """
    if not motorista or not getattr(motorista, 'user_id', None):
        return 0, "Motorista sem usuário vinculado para WebPush"

    try:
        from mobile.services.webpush_service import enviar_notificacao_usuario
        url_destino = "/app/"
        if isinstance(dados_payload, dict) and dados_payload.get("url"):
            url_destino = str(dados_payload["url"])
        enviados, erro_wp = enviar_notificacao_usuario(
            user=motorista.user,
            titulo=titulo,
            mensagem=mensagem,
            url=url_destino,
        )
        return enviados, erro_wp
    except Exception as e:
        logger.error(f"Erro ao tentar WebPush PWA para {motorista.nome_completo}: {e}")
        return 0, str(e)


def enviar_notificacao_push(motorista, titulo, mensagem, tipo='SISTEMA', dados_payload=None):
    """
    Envia uma notificação push via Firebase FCM (APK) e/ou WebPush VAPID (PWA)
    para um motorista específico.
    
    :param motorista: Instância de Motorista
    :param titulo: Título da notificação
    :param mensagem: Corpo da mensagem
    :param tipo: Categoria ('SISTEMA', 'LEMBRETE', 'MANIFESTO', 'ALERTA', 'MANUAL')
    :param dados_payload: Dicionário opcional com dados customizados (ex: {'manifesto_id': '123'})
    :return: (sucesso: bool, message_id_ou_erro: str)
    """
    if not motorista:
        return False, "Motorista não informado"

    # Converte dados extras para string caso haja payload
    payload_clean = {}
    if dados_payload and isinstance(dados_payload, dict):
        for k, v in dados_payload.items():
            payload_clean[str(k)] = str(v) if v is not None else ""

    # Se não possui fcm_token (motorista PWA), tenta envio direto via WebPush
    if not motorista.fcm_token:
        enviados_wp, erro_wp = _tentar_envio_webpush_pwa(motorista, titulo, mensagem, payload_clean)
        if enviados_wp > 0:
            msg_id = f"webpush-pwa ({enviados_wp} disp.)"
            logger.info(f"🌐 WebPush PWA enviado para {motorista.nome_completo}! ({enviados_wp} disp.)")
            NotificacaoPushLog.objects.create(
                motorista=motorista,
                titulo=titulo,
                mensagem=mensagem,
                tipo=tipo,
                dados_payload=payload_clean,
                sucesso=True,
                response_message_id=msg_id
            )
            return True, msg_id

        msg_erro = erro_wp or f"Motorista {motorista.nome_completo} não possui FCM Token nem WebPush PWA ativo."
        logger.info(msg_erro)
        return False, msg_erro

    # Tenta inicializar o Firebase para quem tem fcm_token
    sucesso_init, msg_init = inicializar_firebase()
    if not sucesso_init:
        # Fallback para WebPush caso o motorista também tenha inscrição PWA
        enviados_wp, _ = _tentar_envio_webpush_pwa(motorista, titulo, mensagem, payload_clean)
        if enviados_wp > 0:
            msg_id = f"webpush-pwa-fallback ({enviados_wp} disp.)"
            NotificacaoPushLog.objects.create(
                motorista=motorista,
                titulo=titulo,
                mensagem=mensagem,
                tipo=tipo,
                dados_payload=payload_clean,
                sucesso=True,
                response_message_id=msg_id
            )
            return True, msg_id

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

        # Se o motorista também tiver inscrição WebPush (ex: abriu no PWA), dispara silenciosamente
        _tentar_envio_webpush_pwa(motorista, titulo, mensagem, payload_clean)

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
        update_fields = ['fcm_token']

        # Tenta fallback via WebPush caso ele esteja usando PWA agora
        enviados_wp, _ = _tentar_envio_webpush_pwa(motorista, titulo, mensagem, payload_clean)
        if enviados_wp == 0 and motorista.permissao_notificacao:
            motorista.permissao_notificacao = False
            motorista.permissoes_atualizadas_em = timezone.now()
            update_fields.extend(['permissao_notificacao', 'permissoes_atualizadas_em'])

        motorista.save(update_fields=update_fields)

        if enviados_wp > 0:
            msg_id = f"webpush-pwa-apos-fcm-expirado ({enviados_wp} disp.)"
            NotificacaoPushLog.objects.create(
                motorista=motorista,
                titulo=titulo,
                mensagem=mensagem,
                tipo=tipo,
                dados_payload=payload_clean,
                sucesso=True,
                response_message_id=msg_id
            )
            return True, msg_id

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

        # Tenta fallback via WebPush PWA
        enviados_wp, _ = _tentar_envio_webpush_pwa(motorista, titulo, mensagem, payload_clean)
        if enviados_wp > 0:
            msg_id = f"webpush-pwa-fallback ({enviados_wp} disp.)"
            NotificacaoPushLog.objects.create(
                motorista=motorista,
                titulo=titulo,
                mensagem=mensagem,
                tipo=tipo,
                dados_payload=payload_clean,
                sucesso=True,
                response_message_id=msg_id
            )
            return True, msg_id

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
    Envia notificação push para múltiplos motoristas com fcm_token (APK) ou WebPush (PWA) cadastrado.
    
    :return: Dicionário com estatísticas do envio
    """
    from django.db.models import Q

    # Filtra motoristas com token FCM válido OU inscrição WebPush ativa
    if hasattr(motoristas_qs_ou_lista, 'filter'):
        candidatos = list(
            motoristas_qs_ou_lista.filter(
                (Q(fcm_token__isnull=False) & ~Q(fcm_token='')) |
                Q(user__webpush_subscriptions__isnull=False)
            ).distinct()
        )
    else:
        candidatos = [
            m for m in motoristas_qs_ou_lista
            if m and getattr(m, 'tem_notificacao_ativa', bool(getattr(m, 'fcm_token', None)))
        ]

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
