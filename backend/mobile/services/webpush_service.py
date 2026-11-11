# mobile/services/webpush_service.py

import json
from pywebpush import webpush, WebPushException
from django.conf import settings
from mobile.models import WebPushSubscription
import logging

logger = logging.getLogger(__name__)


VAPID_PRIVATE_KEY = "IQhIJ9Q3ROfee2OfX11f5Rz-9lE_1AYA3TebZwDMEGI"
VAPID_ADMIN_EMAIL = "admin@rdexpresso.com.br"
VAPID_CLAIMS = {
    "sub": f"mailto:{VAPID_ADMIN_EMAIL}"
}


def enviar_notificacao_usuario(user, titulo, mensagem, url="/app/"):
    """
    Envia uma notificação push para todos os subscriptions de um usuário (PWA).
    Retorna (enviados_com_sucesso: int, ultimo_erro: str | None).
    """
    if not user:
        return 0, "Usuário não informado"

    subs = list(WebPushSubscription.objects.filter(user=user))
    if not subs:
        return 0, "Sem assinatura WebPush ativa"

    payload = {
        "title": titulo,
        "body": mensagem,
        "url": url
    }

    enviados = 0
    ultimo_erro = None

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            enviados += 1
        except WebPushException as e:
            ultimo_erro = str(e)
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            # Se endpoint expirou ou removido permanentemente → status 404 / 410
            if status_code in (404, 410):
                logger.info(f"Subscription {sub.id} removida (endpoint expirou: {status_code})")
                sub.delete()
            else:
                logger.warning(f"Falha ao enviar notificação para subscription {sub.id}: {e}")
        except Exception as e:
            ultimo_erro = str(e)
            logger.warning(f"Erro inesperado WebPush subscription {sub.id}: {e}")

    # Se todas as subscriptions expiraram e o motorista não tem FCM token, atualiza flag
    if enviados == 0 and not WebPushSubscription.objects.filter(user=user).exists():
        try:
            motorista = getattr(user, 'motorista_perfil', None)
            if motorista and not motorista.fcm_token and motorista.permissao_notificacao:
                motorista.permissao_notificacao = False
                motorista.save(update_fields=['permissao_notificacao'])
        except Exception:
            pass

    return enviados, ultimo_erro

def enviar_notificacao_grupo(group, titulo, mensagem, url="/app/"):
    """
    Envia uma notificação push para todos os subscriptions de um grupo.
    """
    subs = WebPushSubscription.objects.filter(group=group)
    payload = {
        "title": titulo,
        "body": mensagem,
        "url": url
    }

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh,
                        "auth": sub.auth
                    }
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as e:
            if hasattr(e, "response") and e.response and e.response.status_code == 410:
                logger.info(f"Subscription {sub.id} removida (endpoint expirou)")
                sub.delete()
            else:
                logger.warning(f"Falha ao enviar notificação para subscription {sub.id}: {e}")