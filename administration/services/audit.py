"""Écriture du journal d'audit du back-office."""
import logging

from administration.models import AdminAuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """
    Adresse IP de l'appelant. On ne fait confiance à X-Forwarded-For que si le
    projet tourne derrière un proxy connu (Azure App Service en production).
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        # Le premier élément est l'IP client d'origine.
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action, target="", **details):
    """
    Enregistre une action admin. Ne doit jamais faire échouer la vue appelante :
    une erreur de journalisation est loggée mais avalée.
    """
    try:
        AdminAuditLog.objects.create(
            actor=request.user if request.user.is_authenticated else None,
            action=action,
            target=str(target)[:255],
            details=details or {},
            ip_address=get_client_ip(request),
        )
    except Exception:  # pragma: no cover - robustesse
        logger.exception("Impossible d'écrire dans le journal d'audit (action=%s)", action)
