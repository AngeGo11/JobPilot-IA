"""Contrôle d'accès du back-office."""
import logging
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


def staff_required(view_func):
    """
    Réserve la vue aux membres de l'équipe (`is_staff`).

    On renvoie un 403 plutôt qu'une redirection vers la connexion quand
    l'utilisateur est déjà authentifié : cela évite de révéler l'existence des
    URL du back-office à un compte candidat, et les tentatives sont loggées.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not user.is_staff or not user.is_active:
            logger.warning(
                "Accès back-office refusé pour %s sur %s", user.email, request.path
            )
            raise PermissionDenied("Accès réservé à l'équipe JobPilot-AI.")
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    """Pour les actions les plus sensibles (modification des paramètres du site)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not user.is_superuser or not user.is_active:
            logger.warning(
                "Action superadmin refusée pour %s sur %s", user.email, request.path
            )
            raise PermissionDenied("Action réservée aux super-administrateurs.")
        return view_func(request, *args, **kwargs)

    return wrapper
