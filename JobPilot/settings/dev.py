"""
Réglages de développement local.

Objectif : un poste de travail ne doit jamais pouvoir toucher la production par
inadvertance, et doit fonctionner sans Redis ni SMTP.
"""
from .base import *  # noqa: F401,F403
from .base import DATABASES, env_bool

DEBUG = env_bool("DEBUG", default=True)

# Aucune redirection HTTPS ni cookie sécurisé en local : `runserver` sert en HTTP.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_PROXY_SSL_HEADER = None

ALLOWED_HOSTS = ["*"]

# Garde-fou : refuser de démarrer si la base pointe sur la production.
# Sans cela, un DATABASE_URL laissé dans le .env fait travailler tout le poste
# de développement — migrations comprises — sur les données réelles.
_host = (DATABASES["default"].get("HOST") or "").lower()
_LOCAL_HOSTS = ("", "localhost", "127.0.0.1", "::1", "db", "postgres", "host.docker.internal")

if _host not in _LOCAL_HOSTS and not env_bool("ALLOW_REMOTE_DB", default=False):
    raise RuntimeError(
        f"\n\n  Base distante détectée en développement : « {_host} ».\n"
        "  Les migrations et les commandes de seed s'appliqueraient à la production.\n\n"
        "  Corrigez DATABASE_URL pour pointer sur votre base locale, par exemple :\n"
        "    DATABASE_URL=postgres://axel:motdepasse@127.0.0.1:5433/jobpilot_db\n\n"
        "  Si l'accès distant est réellement voulu (lecture ponctuelle) :\n"
        "    ALLOW_REMOTE_DB=true\n"
    )


# Médias en local : sans cette surcharge, un .env contenant AZURE_ACCOUNT_NAME
# ferait écrire les CV de test dans le conteneur Blob de production.
STORAGES = {
    **globals().get("STORAGES", {}),
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MEDIA_URL = "/media/"
