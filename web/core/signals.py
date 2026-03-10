"""
Auth event logging via Django signals.

Logs login, logout, and failed login attempts so they flow through
the OTel logging pipeline into Elasticsearch.
"""
import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

logger = logging.getLogger('core.auth')


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    ip = _get_client_ip(request)
    logger.info("User logged in: %s (id=%s) from %s", user.username, user.pk, ip)


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if user:
        logger.info("User logged out: %s (id=%s)", user.username, user.pk)
    else:
        logger.info("User logged out (anonymous session)")


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    ip = _get_client_ip(request) if request else 'unknown'
    username = credentials.get('username', 'unknown')
    logger.warning("Failed login attempt: username=%s from %s", username, ip)


def _get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')
