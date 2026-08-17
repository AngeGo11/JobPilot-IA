"""Middleware d'application du mode maintenance."""
import logging

from django.shortcuts import render
from django.urls import reverse

from administration.models import SiteSettings

logger = logging.getLogger(__name__)

# Préfixes toujours accessibles : sans ça, activer la maintenance couperait
# l'accès au back-office (et donc le moyen de la désactiver) et bloquerait les
# webhooks Stripe, ce qui ferait perdre des paiements.
ALWAYS_ALLOWED_PREFIXES = (
    "/administration/",
    "/admin/",
    "/subscriptions/webhook",
    "/static/",
    "/media/",
)


class MaintenanceModeMiddleware:
    """Renvoie une page 503 aux visiteurs quand le mode maintenance est actif."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            settings_obj = SiteSettings.load()
            response = render(
                request,
                "administration/maintenance.html",
                {"message": settings_obj.maintenance_message},
                status=503,
            )
            response["Retry-After"] = "3600"
            return response
        return self.get_response(request)

    def _should_block(self, request):
        path = request.path
        if path.startswith(ALWAYS_ALLOWED_PREFIXES):
            return False
        try:
            if not SiteSettings.load().maintenance_mode:
                return False
        except Exception:  # noqa: BLE001 - table absente avant la 1re migration
            return False
        # L'équipe continue de naviguer normalement pour vérifier le site.
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff:
            return False
        # La déconnexion reste possible pour ne pas piéger une session ouverte.
        try:
            if path == reverse("logout"):
                return False
        except Exception:  # pragma: no cover
            pass
        return True
