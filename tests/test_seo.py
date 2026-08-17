"""Garde-fous SEO : balises head, sitemap, robots.txt et analytics."""
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse


class HomeHeadTests(TestCase):
    def setUp(self):
        self.html = self.client.get(reverse('home')).content.decode()

    def test_title_optimise(self):
        self.assertIn(
            '<title>JobPilot-AI – Matching emploi IA | Trouvez votre job automatiquement</title>',
            self.html,
        )

    def test_meta_description_longueur_recommandee(self):
        import re

        match = re.search(r'<meta name="description" content="([^"]+)"', self.html)
        self.assertIsNotNone(match, "meta description absente de la home")
        self.assertTrue(150 <= len(match.group(1)) <= 160, len(match.group(1)))

    def test_canonical_absolue_sur_le_domaine_configure(self):
        self.assertIn('<link rel="canonical" href="https://jobpilot-ai.fr/">', self.html)

    def test_open_graph_present(self):
        for prop in ('og:title', 'og:description', 'og:image', 'og:url', 'og:type'):
            self.assertIn(f'property="{prop}"', self.html)

    def test_og_image_est_une_url_absolue(self):
        # Les crawlers sociaux refusent les chemins relatifs ; STATIC_URL sans
        # slash initial produirait « https://domainestatic/... ».
        self.assertIn(
            '<meta property="og:image" content="https://jobpilot-ai.fr/static/images/og-image.png">',
            self.html,
        )

    def test_h1_sans_faute(self):
        self.assertNotIn("offres d'emplois", self.html)


class RobotsSitemapTests(TestCase):
    def test_robots_txt_sert_du_texte_et_pointe_le_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertIn('Sitemap: https://jobpilot-ai.fr/sitemap.xml', response.content.decode())

    def test_sitemap_liste_les_pages_publiques_en_absolu(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('<loc>https://jobpilot-ai.fr/</loc>', body)
        self.assertIn('<loc>https://jobpilot-ai.fr/subscriptions/pricing/</loc>', body)
        self.assertNotIn('example.com', body)


class AnalyticsTests(TestCase):
    def test_pas_de_script_ga_sans_identifiant(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertNotIn('googletagmanager.com', html)

    @override_settings(GA_MEASUREMENT_ID='G-TEST12345')
    def test_script_ga_injecte_avec_consentement_refuse_par_defaut(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('gtag/js?id=G-TEST12345', html)
        self.assertIn("'analytics_storage': 'denied'", html)


class PricingDiscoverabilityTests(TestCase):
    """La page Tarifs doit être atteignable sans être connecté.

    Elle ne figurait que dans la navigation authentifiée : un visiteur ne
    pouvait pas connaître les prix, ce qui en faisait une page orpheline (ni
    parcourue par un humain, ni bien évaluée par un moteur).
    """

    def test_lien_tarifs_dans_les_pages_publiques(self):
        pricing_url = reverse('pricing')
        for page in ('home', 'cgu', 'mentions_legales', 'politique_confidentialite'):
            with self.subTest(page=page):
                html = self.client.get(reverse(page)).content.decode()
                self.assertIn(f'href="{pricing_url}"', html)

    def test_apercu_tarifaire_sur_l_accueil(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('tarifs-titre', html)
        for price in ('2,99', '5,99', '14,99'):
            self.assertIn(price, html)


class CspAnalyticsTests(SimpleTestCase):
    """
    La CSP doit autoriser les points de collecte de GA4.

    Constaté en production : le script se chargeait mais chaque envoi était
    bloqué — « Refused to connect to https://region1.google-analytics.com/…
    because it does not appear in the connect-src directive ». La mesure était
    donc entièrement inopérante, alors que tout paraissait installé.
    """

    def _connect_src(self):
        from JobPilot.middleware import _policy

        for directive in _policy().split(";"):
            directive = directive.strip()
            if directive.startswith("connect-src"):
                return directive
        return ""

    def test_regional_collect_endpoints_are_allowed(self):
        connect = self._connect_src()
        self.assertIn(
            "https://*.google-analytics.com", connect,
            "sans le motif génerique, region1/region2… sont bloqués",
        )
        self.assertIn("https://*.analytics.google.com", connect)

    def test_tag_script_origin_is_allowed(self):
        from JobPilot.middleware import _policy

        script = next(
            d.strip() for d in _policy().split(";") if d.strip().startswith("script-src")
        )
        self.assertIn("googletagmanager.com", script)

    def test_policy_still_locks_the_dangerous_directives(self):
        """Élargir connect-src ne doit pas relâcher le reste."""
        from JobPilot.middleware import _policy

        politique = _policy()
        for attendu in ("frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'"):
            self.assertIn(attendu, politique)
