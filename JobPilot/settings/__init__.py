"""
Aiguillage des réglages selon l'environnement.

`DJANGO_SETTINGS_MODULE` reste `JobPilot.settings` : la commande de démarrage
Azure, `manage.py`, `wsgi.py` et `asgi.py` continuent de fonctionner sans
modification. Seul le contenu chargé change.

    ENVIRONMENT=production  → prod.py
    ENVIRONMENT=*           → dev.py
    manage.py test          → test.py (détecté automatiquement)

Pour forcer un module précis :  DJANGO_SETTINGS_MODULE=JobPilot.settings.prod
"""
import os
import sys

from dotenv import load_dotenv

# Charger le .env AVANT de choisir le module : sans cela, `ENVIRONMENT` n'est lu
# que dans les variables du shell, et la valeur inscrite dans .env est
# silencieusement ignorée — l'aiguillage retomberait toujours sur dev.py en
# local, quel que soit le contenu du fichier.
load_dotenv()

_environment = (os.getenv("ENVIRONMENT") or "development").strip().lower()

# Une exécution de tests ne doit jamais hériter du cache Redis ni des réglages
# de production, quel que soit le contenu du .env de la machine.
_is_test_run = "test" in sys.argv or os.getenv("DJANGO_TESTING") == "1"

if _is_test_run:
    from .test import *  # noqa: F401,F403
elif _environment == "production":
    from .prod import *  # noqa: F401,F403
else:
    from .dev import *  # noqa: F401,F403
