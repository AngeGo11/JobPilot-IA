"""
Signaux pour l'app users.
Déclenche la modale de bienvenue à la première connexion (après inscription).
"""
from django.dispatch import receiver
from allauth.account.signals import user_signed_up


@receiver(user_signed_up)
def on_user_signed_up(request, user, **kwargs):
    """
    Lors d'une inscription via Allauth (ex. Social Login Google/GitHub/LinkedIn),
    on marque la session pour afficher la modale de bienvenue au prochain accès au dashboard.
    """
    if request is not None:
        request.session["show_welcome_modal"] = True
