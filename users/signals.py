"""
Signaux pour l'app users.
Déclenche la modale de bienvenue et envoie l'email de bienvenue à la première inscription.
"""
from django.dispatch import receiver
from allauth.account.signals import user_signed_up

from .services.welcome_email import send_welcome_email


@receiver(user_signed_up)
def on_user_signed_up(request, user, **kwargs):
    """
    Lors d'une inscription via Allauth (ex. Social Login Google/GitHub/LinkedIn),
    on marque la session pour la modale de bienvenue et on envoie l'email de bienvenue.
    """
    if request is not None:
        request.session["show_welcome_modal"] = True
    send_welcome_email(user, request=request)
