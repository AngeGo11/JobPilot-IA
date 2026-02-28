"""
Envoi du mail de bienvenue à la première inscription / première connexion.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def get_site_url(request=None):
    """Retourne l'URL de base du site (pour les liens dans les mails)."""
    if request:
        return request.build_absolute_uri("/").rstrip("/")
    try:
        from django.contrib.sites.shortcuts import get_current_site
        site = get_current_site(None)
        return f"https://{site.domain}" if not site.domain.startswith("http") else site.domain.rstrip("/")
    except Exception:
        return getattr(settings, "SITE_URL", "https://jobpilot-ai.fr")


def send_welcome_email(user, request=None):
    """
    Envoie l'email de bienvenue à l'utilisateur après sa première inscription.
    Appelé depuis le formulaire d'inscription et le signal allauth user_signed_up.
    """
    email = getattr(user, "email", None) if user else None
    if not user or not email:
        logger.warning("send_welcome_email skipped: no user or no email")
        return
    site_url = get_site_url(request)
    context = {"user": user, "site_url": site_url}
    html_content = render_to_string("account/email/welcome_message.html", context)
    subject = "Bienvenue sur JobPilot-AI"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "jobpilot-ai <noreply@jobpilot-ai.fr>")
    try:
        msg = EmailMultiAlternatives(subject, strip_html_to_plain(html_content), from_email, [email])
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        logger.info("Welcome email sent to %s", email)
    except Exception as e:
        logger.exception("Failed to send welcome email to %s: %s", email, e)
        if getattr(settings, "DEBUG", False):
            raise


def strip_html_to_plain(html):
    """Extrait un texte lisible depuis du HTML (pour la version plain du mail)."""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500] if text else "Bienvenue sur JobPilot-AI."
