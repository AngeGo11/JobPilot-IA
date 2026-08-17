"""
Réglages de la suite de tests.

Chargés automatiquement par `manage.py test` (voir __init__.py). Ils rendent la
suite indépendante de la machine : ni Redis, ni SMTP, ni `collectstatic`
préalable ne sont nécessaires.
"""
import os

import dj_database_url

from .base import *  # noqa: F401,F403

DEBUG = False

# --- Base de données -------------------------------------------------------
# Le lanceur de tests CRÉE puis DÉTRUIT une base « test_<nom> » sur l'hôte
# configuré. Avec le DATABASE_URL de production dans le .env, chaque
# `manage.py test` allait donc créer une base sur le serveur Azure de
# production — et chaque requête payait la latence réseau.
#
# On force ici un hôte local, sauf TEST_DATABASE_URL explicite (utilisé par la
# CI, qui fournit son propre service PostgreSQL).
_test_database_url = os.getenv("TEST_DATABASE_URL")  # noqa: F405
if _test_database_url:
    DATABASES = {"default": dj_database_url.config(default=_test_database_url)}  # noqa: F405
else:
    _remote = (DATABASES["default"].get("HOST") or "").lower() not in (  # noqa: F405
        "", "localhost", "127.0.0.1", "::1", "db", "postgres",
    )
    if _remote:
        DATABASES = {  # noqa: F405
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.getenv("DB_NAME", "jobpilot_db"),  # noqa: F405
                "USER": os.getenv("DB_USER", "axel"),  # noqa: F405
                "PASSWORD": os.getenv("DB_PASSWORD", "password123"),  # noqa: F405
                "HOST": "127.0.0.1",
                "PORT": os.getenv("DB_PORT_HOST", "5433"),  # noqa: F405
            }
        }

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_PROXY_SSL_HEADER = None
ALLOWED_HOSTS = ["*"]

# Cache mémoire : les compteurs de rate limit doivent repartir de zéro entre
# deux exécutions, et un Redis partagé ferait échouer les tests en parallèle.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jobpilot-tests",
    }
}

# Les tâches s'exécutent immédiatement et propagent leurs exceptions : les
# tests vérifient le comportement métier, pas la mécanique de la file.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = ""

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Le stockage manifeste de WhiteNoise exige un `collectstatic` préalable et
# lève sur chaque {% static %} sans lui.
# `STORAGES` n'existe dans base.py que si AZURE_ACCOUNT_NAME est défini : on
# repart donc du dictionnaire s'il est là, d'un stockage fichier sinon.
STORAGES = {
    **globals().get("STORAGES", {}),
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Hachage rapide : la suite crée des dizaines de comptes, PBKDF2 domine sinon
# le temps d'exécution.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Aucun tracking pendant les tests, même si la variable est présente dans
# l'environnement du développeur.
GA_MEASUREMENT_ID = ""
SITE_URL = "https://jobpilot-ai.fr"
