"""En-têtes de sécurité que Django ne pose pas lui-même.

`SecurityMiddleware` couvre HSTS, nosniff et le referrer ; il ne gère ni
Content-Security-Policy ni Permissions-Policy. Ce module comble ce manque sans
dépendance supplémentaire.

Limite assumée de la CSP actuelle : `script-src` et `style-src` contiennent
`'unsafe-inline'`. Les gabarits utilisent des gestionnaires d'événements en
ligne (`onclick="togglePassword()"`) et des attributs `style=""`, et un nonce ne
couvre PAS les gestionnaires en ligne — les autoriser exige `'unsafe-inline'`.
La politique reste utile pour autant : elle verrouille les origines autorisées,
interdit l'inclusion en iframe, les plugins et la réécriture de `<base>`.
Pour passer à une CSP à nonce, il faut d'abord déplacer ces gestionnaires dans
des `addEventListener` — c'est documenté dans docs/performance-securite.md.
"""
from django.conf import settings

#: Origines tierces encore nécessaires, avec la raison de leur présence.
#
# Google Analytics 4 : le script vient de googletagmanager, mais les mesures
# partent vers un point de collecte RÉGIONAL — region1.google-analytics.com,
# region2, etc. selon la localisation du visiteur. Lister le seul domaine
# `www.google-analytics.com` laissait donc le script se charger sans qu'aucune
# donnée ne soit transmise : le navigateur bloquait chaque envoi avec
# « Refused to connect … does not appear in the connect-src directive ».
# D'où les motifs génériques, conformes à la documentation Google.
_GA_SCRIPT = ("https://*.googletagmanager.com",)
_GA_CONNECT = (
    "https://*.google-analytics.com",
    "https://*.analytics.google.com",
    "https://*.googletagmanager.com",
)
_TINYMCE = ("https://cdn.tiny.cloud", "https://sp.tinymce.com")  # éditeur de lettres
_CONFETTI = ("https://cdn.jsdelivr.net",)  # animation de succès du tableau de bord


def _policy() -> str:
    script = ["'self'", "'unsafe-inline'", *_GA_SCRIPT, *_TINYMCE, *_CONFETTI]
    style = ["'self'", "'unsafe-inline'", *_TINYMCE]
    connect = ["'self'", *_GA_CONNECT, *_TINYMCE]

    directives = [
        "default-src 'self'",
        "script-src " + " ".join(script),
        "style-src " + " ".join(style),
        # GA4 utilise aussi des pixels en repli quand `fetch` est indisponible ;
        # `https:` les couvre déjà.
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src " + " ".join(connect),
        "frame-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
    if getattr(settings, "SECURE_SSL_REDIRECT", False):
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


#: Fonctionnalités navigateur dont le site n'a aucun usage.
PERMISSIONS_POLICY = (
    "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
    "encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), usb=(), "
    "xr-spatial-tracking=()"
)


class SecurityHeadersMiddleware:
    """Pose Content-Security-Policy et Permissions-Policy sur chaque réponse.

    `CSP_REPORT_ONLY=true` bascule la CSP en observation : les violations sont
    remontées dans la console du navigateur sans rien bloquer. C'est le réglage
    à utiliser pendant quelques jours après une modification de gabarit qui
    introduit une origine tierce.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = _policy()
        self.header = (
            "Content-Security-Policy-Report-Only"
            if getattr(settings, "CSP_REPORT_ONLY", False)
            else "Content-Security-Policy"
        )

    def __call__(self, request):
        response = self.get_response(request)
        # L'admin Django embarque ses propres scripts/styles ; la politique
        # globale le couvre, mais on ne remplace jamais un en-tête déjà posé.
        response.setdefault(self.header, self.policy)
        response.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response
