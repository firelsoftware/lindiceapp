"""Envio de notificacoes Web Push (VAPID).

Desligado automaticamente se as chaves VAPID nao estiverem configuradas,
entao nada quebra quando o recurso ainda nao foi ativado.
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def push_enabled():
    return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)


def send_web_push(user, title, body, url="/"):
    if not push_enabled() or user is None:
        return

    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        logger.warning("pywebpush nao instalado; push ignorado.")
        return

    subscriptions = list(user.push_subscriptions.all())
    if not subscriptions:
        return

    payload = json.dumps({"title": title, "body": body, "url": url})

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_ADMIN_EMAIL},
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                sub.delete()  # inscricao expirada
            else:
                logger.warning("Falha no web push: %s", exc)
        except Exception:
            logger.exception("Erro inesperado no web push")
