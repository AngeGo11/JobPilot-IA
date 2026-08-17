"""Vues du projet qui n'appartiennent à aucune application métier."""
import logging

from django.views.generic import TemplateView

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    """Page d'accueil publique.

    Elle était servie par un `TemplateView` sans contexte ; elle a désormais
    besoin des témoignages clients publiés. La requête reste triviale (quelques
    lignes, filtrées et ordonnées en base) et la section disparaît d'elle-même
    tant qu'aucun témoignage n'est publié.
    """

    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            from administration.models import Testimonial

            context["testimonials"] = list(
                Testimonial.objects.filter(is_published=True)[:6]
            )
        except Exception:  # noqa: BLE001
            # Le site doit rester servable avant l'application des migrations.
            logger.debug("Témoignages indisponibles", exc_info=True)
            context["testimonials"] = []
        return context
