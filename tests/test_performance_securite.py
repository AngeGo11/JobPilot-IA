"""Garde-fous sur les acquis performance, accessibilité et sécurité.

Ces tests protègent des régressions faciles à réintroduire : recoller un
`<script src="https://cdn...">` dans un gabarit, remettre le logo de 2 Mo,
ou casser l'ordre des titres en changeant une balise pour un effet visuel.
"""
import re

from django.test import TestCase, override_settings
from django.urls import reverse

from administration.models import Testimonial

# Pages publiques rendues sans authentification.
PUBLIC_URLS = ["home", "pricing", "login", "register", "cgu", "mentions_legales",
               "politique_confidentialite"]


class PublicPagesMixin:
    """Les écrans de connexion et d'inscription affichent le bouton Google.

    `{% provider_login_url 'google' %}` lève si aucune application sociale n'est
    enregistrée : on en crée une, sans quoi ces deux pages sont intestables.
    """

    @classmethod
    def setUpTestData(cls):
        from allauth.socialaccount.models import SocialApp
        from django.contrib.sites.models import Site

        app = SocialApp.objects.create(
            provider="google", name="Google (test)", client_id="x", secret="y"
        )
        app.sites.add(Site.objects.get_current())


class ThirdPartyAssetTests(PublicPagesMixin, TestCase):
    """Plus aucune ressource bloquante servie par un tiers."""

    FORBIDDEN = ("cdn.tailwindcss.com", "cdnjs.cloudflare.com", "fonts.googleapis.com",
                 "fonts.gstatic.com", "svgrepo.com")

    def test_aucune_origine_tierce_sur_les_pages_publiques(self):
        for name in PUBLIC_URLS:
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                for host in self.FORBIDDEN:
                    self.assertNotIn(host, html)

    def test_la_feuille_compilee_est_servie(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("css/app.css", html)
        self.assertIn("css/icons.css", html)

    def test_le_logo_de_deux_megaoctets_nest_plus_reference(self):
        for name in PUBLIC_URLS:
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertNotIn("images/Logo.png", html)


class HeadingOrderTests(PublicPagesMixin, TestCase):
    """axe-core `heading-order` : un titre ne saute jamais de niveau."""

    def test_hierarchie_des_titres(self):
        for name in PUBLIC_URLS:
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                levels = [int(m) for m in re.findall(r"<h([1-6])[\s>]", html)]
                self.assertTrue(levels, "aucun titre trouvé")
                self.assertEqual(levels[0], 1, "la page doit commencer par un h1")
                self.assertEqual(levels.count(1), 1, "un seul h1 par page")
                for previous, current in zip(levels, levels[1:]):
                    self.assertLessEqual(
                        current, previous + 1,
                        f"saut de h{previous} à h{current} sur la page {name}",
                    )


class SecurityHeaderTests(TestCase):
    def test_csp_et_permissions_policy_sur_toutes_les_reponses(self):
        response = self.client.get(reverse("home"))
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        self.assertIn("camera=()", response["Permissions-Policy"])

    @override_settings(CSP_REPORT_ONLY=True)
    def test_mode_observation(self):
        # L'en-tête est calculé à l'instanciation du middleware : on en construit
        # un neuf plutôt que de passer par le client de test, dont la pile est
        # déjà montée avec l'ancien réglage.
        from django.http import HttpResponse
        from django.test import RequestFactory

        from JobPilot.middleware import SecurityHeadersMiddleware

        middleware = SecurityHeadersMiddleware(lambda request: HttpResponse("ok"))
        response = middleware(RequestFactory().get("/"))
        self.assertIn("Content-Security-Policy-Report-Only", response.headers)
        self.assertNotIn("Content-Security-Policy", response.headers)


class CompressionTests(TestCase):
    def test_reponse_html_compressee(self):
        response = self.client.get(reverse("home"), headers={"accept-encoding": "gzip"})
        self.assertEqual(response["Content-Encoding"], "gzip")


class TestimonialSectionTests(TestCase):
    def test_section_absente_sans_temoignage_publie(self):
        Testimonial.objects.create(
            author_name="Brouillon", author_role="Testeur", quote="…",
            consent_reference="aucun", is_published=False,
        )
        html = self.client.get(reverse("home")).content.decode()
        self.assertNotIn("temoignages-titre", html)

    def test_section_rendue_avec_un_temoignage_publie(self):
        Testimonial.objects.create(
            author_name="Lucas B.",
            author_role="Développeur full-stack",
            quote="J'ai reçu trois réponses la première semaine.",
            result_metric="3 entretiens en 2 semaines",
            consent_reference="accord par mail du 12/03/2026",
            is_published=True,
        )
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("temoignages-titre", html)
        self.assertIn("J&#x27;ai reçu trois réponses la première semaine.", html)
        self.assertIn("3 entretiens en 2 semaines", html)


class PricingComparisonTests(TestCase):
    def test_tableau_comparatif_present(self):
        html = self.client.get(reverse("pricing")).content.decode()
        self.assertIn("comparatif-titre", html)
        self.assertIn("<caption", html)
        for plan in ("Gratuit", "Pass 24h", "Sprint", "Pro", "Pack"):
            self.assertIn(plan, html)
        # Le Pack donne des crédits, pas un abonnement : donc pas d'alertes email.
        self.assertIn("Alertes email sur les nouvelles offres", html)
