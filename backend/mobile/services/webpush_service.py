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
    Envia uma notificação push para todos os subscriptions de um usuário.
    """
    subs = WebPushSubscription.objects.filter(user=user)
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
            # Se endpoint expirou ou removido permanentemente → status 410
            if hasattr(e, "response") and e.response and e.response.status_code == 410:
                logger.info(f"Subscription {sub.id} removida (endpoint expirou)")
                sub.delete()
            else:
                logger.warning(f"Falha ao enviar notificação para subscription {sub.id}: {e}")

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