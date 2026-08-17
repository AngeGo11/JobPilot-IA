"""Sitemaps XML du site public.

Le framework `sitemaps` s'appuie normalement sur `django.contrib.sites` pour
construire les URLs absolues. Ici le domaine fait déjà autorité dans
`settings.SITE_URL` (variable d'environnement) : on injecte donc un objet Site
non persisté pour éviter toute divergence avec la table `django_site`, qui
contient encore `example.com` sur une base fraîchement migrée.
"""
from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class _SettingsSite:
    """Site minimal (attribut `domain`) construit depuis `settings.SITE_URL`."""

    def __init__(self):
        self.domain = (
            settings.SITE_URL.replace('https://', '').replace('http://', '').rstrip('/')
        )
        self.name = self.domain


class StaticViewSitemap(Sitemap):
    """Pages publiques statiques, indexables."""

    protocol = 'https'

    #: nom de l'URL -> (priorité, fréquence de changement)
    PAGES = {
        'home': (1.0, 'weekly'),
        'pricing': (0.8, 'monthly'),
        'login': (0.5, 'yearly'),
        'register': (0.7, 'yearly'),
        'cgu': (0.3, 'yearly'),
        'mentions_legales': (0.3, 'yearly'),
        'politique_confidentialite': (0.3, 'yearly'),
    }

    def items(self):
        return list(self.PAGES)

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return self.PAGES[item][0]

    def changefreq(self, item):
        return self.PAGES[item][1]

    def get_urls(self, page=1, site=None, protocol=None):
        # Quel que soit le site fourni (RequestSite ou entrée `django_site`),
        # on force le domaine canonique configuré.
        return super().get_urls(page=page, site=_SettingsSite(), protocol=protocol)


SITEMAPS = {'static': StaticViewSitemap}
