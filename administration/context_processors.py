"""Expose les paramètres du site à tous les templates."""
import logging

from administration.models import SiteSettings

logger = logging.getLogger(__name__)


def site_settings(request):
    """
    Rend `site_settings` disponible partout (bandeau d'information, email de
    contact). Robuste à l'absence de table : le projet doit rester servable
    avant l'application de la première migration.
    """
    try:
        return {"site_settings": SiteSettings.load()}
    except Exception:  # noqa: BLE001
        logger.debug("Paramètres du site indisponibles", exc_info=True)
        return {"site_settings": None}
