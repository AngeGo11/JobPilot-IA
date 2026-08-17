"""
Réglages de production.

Distinction volontaire entre deux niveaux de gravité :

- ce qui ouvre un trou de sécurité fait **échouer le démarrage** ;
- ce qui dégrade la robustesse écrit un **avertissement** dans les logs.

Un garde-fou qui coupe un site en ligne parce qu'une variable optionnelle
manque cause plus de dégâts que le problème qu'il prévient.
"""
import logging
import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR, CELERY_BROKER_URL, DATABASES, REDIS_URL, env_bool

logger = logging.getLogger(__name__)

DEBUG = False

# --- Garde-fou : « production » sur un poste de développement ---
# Un `.env` local contenant ENVIRONMENT=production charge ce module sur la
# machine du développeur. Le garde-fou de dev.py ne s'applique alors pas, et un
# `manage.py migrate` toucherait la base de production.
#
# Azure App Service définit WEBSITE_INSTANCE_ID sur chaque instance : sa
# présence distingue le vrai serveur du poste local de façon fiable.
_on_azure = bool(os.getenv("WEBSITE_INSTANCE_ID") or os.getenv("WEBSITE_SITE_NAME"))
_db_host = (DATABASES["default"].get("HOST") or "").lower()
_db_is_remote = _db_host not in ("", "localhost", "127.0.0.1", "::1", "db", "postgres")

if _db_is_remote and not _on_azure and not env_bool("ALLOW_REMOTE_DB", default=False):
    raise RuntimeError(
        f"\n\n  ENVIRONMENT=production hors de l'hébergeur, avec une base distante :\n"
        f"    « {_db_host} »\n\n"
        "  Toute commande (migrate, shell, seed) s'appliquerait à la production.\n\n"
        "  Sur votre poste : passez ENVIRONMENT=development dans .env,\n"
        "  ou utilisez `source scripts/dev-env.sh` / `make`.\n\n"
        "  Si l'accès distant est réellement voulu : ALLOW_REMOTE_DB=true\n"
    )

# --- Bloquant : le site ne doit pas démarrer dans cet état ---
_fatal = []

if "*" in ALLOWED_HOSTS:  # noqa: F405
    _fatal.append(
        "ALLOWED_HOSTS contient '*', ce qui expose le site aux attaques par "
        "en-tête Host. Renseignez SITE_URL."
    )

if not SECRET_KEY or len(SECRET_KEY) < 40:  # noqa: F405
    _fatal.append("DJANGO_SECRET_KEY est absente ou trop courte (40 caractères minimum).")

if _fatal:
    raise RuntimeError(
        "Configuration de production invalide :\n  - " + "\n  - ".join(_fatal)
    )

# --- Non bloquant : dégradation connue, signalée dans les logs ---
if not REDIS_URL:
    logger.warning(
        "REDIS_URL absente : le cache est local à chaque worker. Le compteur de "
        "requêtes Gemini devient effectif × nombre de workers, et le token "
        "France Travail est redemandé par chaque processus. À configurer dès "
        "que gunicorn tourne avec plus d'un worker."
    )

if not CELERY_BROKER_URL:
    logger.warning(
        "CELERY_BROKER_URL absente : les tâches longues s'exécutent dans le "
        "cycle requête/réponse et immobilisent un worker web pendant toute "
        "leur durée."
    )

# --- Sécurité HTTPS ---
# Explicite ici plutôt que déduite d'un booléen calculé dans base.py : en
# production, ces valeurs ne dépendent d'aucune variable d'environnement.
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

STATIC_ROOT = BASE_DIR / "staticfiles"
