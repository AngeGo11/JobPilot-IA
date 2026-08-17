"""Contexte SEO / analytics disponible dans tous les templates."""
from django.conf import settings


def seo(request):
    """Expose l'URL canonique de la page courante et l'ID de mesure GA4.

    L'URL canonique est bâtie sur `SITE_URL` (et non sur l'hôte de la requête)
    pour que www / apex / ngrok pointent tous vers le même document, et sur
    `request.path` afin d'écarter les paramètres de tracking (utm_*, gclid…).
    """
    site_url = settings.SITE_URL.rstrip('/')
    path = getattr(request, 'path', '/') or '/'
    return {
        'SITE_URL': site_url,
        'CANONICAL_URL': f'{site_url}{path}',
        'GA_MEASUREMENT_ID': getattr(settings, 'GA_MEASUREMENT_ID', ''),
    }
