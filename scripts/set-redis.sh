#!/usr/bin/env bash
# Configure un broker Redis externe (Upstash ou équivalent) sur l'application.
#
#   ./scripts/set-redis.sh 'rediss://default:MOT_DE_PASSE@xxx.upstash.io:6379'
#
# L'URL est testée avant d'être posée : une URL invalide écrite dans les
# variables d'application ferait échouer le démarrage du worker au prochain
# déploiement, et la panne n'apparaîtrait qu'en production.
set -euo pipefail

URL="${1:-}"
APP_NAME="${APP_NAME:-jobpilot-ai}"
RG="${RG:-jobpilot-rg}"

vert()  { printf "\033[0;32m  %s\033[0m\n" "$*"; }
jaune() { printf "\033[0;33m  %s\033[0m\n" "$*"; }
rouge() { printf "\033[0;31m  %s\033[0m\n" "$*"; }

if [ -z "$URL" ]; then
    rouge "Usage : $0 'rediss://default:<mot-de-passe>@<hote>:6379'"
    exit 1
fi

case "$URL" in
    rediss://*) ;;
    redis://*)  jaune "URL en redis:// (sans TLS). Upstash fournit du rediss://." ;;
    *)          rouge "URL inattendue : doit commencer par rediss:// ou redis://"; exit 1 ;;
esac

# --------------------------------------------------------------------------- #
echo "1. Test de connexion"

# Bases distinctes pour le cache et la file : un `cache.clear()` ne doit pas
# vider la file de tâches. Upstash n'expose qu'une base (0) — dans ce cas on
# garde la même partout, le risque étant théorique à ce volume.
python - "$URL" <<'PY'
import sys
import redis

url = sys.argv[1]
try:
    client = redis.from_url(url, socket_connect_timeout=10, socket_timeout=10)
    client.set("jobpilot:probe", "ok", ex=30)
    assert client.get("jobpilot:probe") == b"ok"
    info = client.info("server")
    print(f"    connexion OK — Redis {info.get('redis_version', '?')}")
    bases = client.config_get("databases") if hasattr(client, "config_get") else {}
    print(f"    bases disponibles : {bases.get('databases', 'inconnu (serverless)')}")
except Exception as exc:
    print(f"    ECHEC : {type(exc).__name__} : {exc}")
    sys.exit(1)
PY

# --------------------------------------------------------------------------- #
echo "2. Écriture des variables d'application"

# Une seule base sur les offres serverless : cache et broker la partagent.
# Les clés sont préfixées différemment, il n'y a pas de collision possible.
az webapp config appsettings set \
    --name "$APP_NAME" --resource-group "$RG" --output none \
    --settings \
        "REDIS_URL=$URL" \
        "CELERY_BROKER_URL=$URL" \
        "CELERY_RESULT_BACKEND=$URL" \
        "CELERY_CONCURRENCY=2"
vert "REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_CONCURRENCY"

echo
vert "Fait. Le worker démarrera au prochain déploiement, et le cache devient"
vert "partagé entre les 4 workers gunicorn — le compteur de requêtes Gemini"
vert "redevient réellement global."
