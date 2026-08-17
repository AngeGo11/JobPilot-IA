"""
Éprouve une URL de broker Celery.

Le cache Django accepte des URL que kombu refuse — notamment une URL
`rediss://` sans `ssl_cert_reqs`. Tester uniquement le cache laisserait donc
passer une configuration où le site fonctionne mais où le worker refuse de
démarrer : une panne partielle, visible seulement en production.

    CELERY_BROKER_URL=rediss://... python scripts/check_broker.py
"""
import os
import sys


def main():
    url = os.environ.get("CELERY_BROKER_URL", "")
    if not url:
        print("    CELERY_BROKER_URL absente")
        return 1

    try:
        from kombu import Connection
    except ImportError:
        print("    kombu absent : `pip install -r requirements/base.txt`")
        return 1

    try:
        with Connection(url) as connexion:
            connexion.ensure_connection(max_retries=2)
    except Exception as exc:  # noqa: BLE001 - on rapporte tout échec tel quel
        print(f"    broker Celery ECHEC : {type(exc).__name__} : {exc}")
        return 1

    print("    broker Celery : OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
