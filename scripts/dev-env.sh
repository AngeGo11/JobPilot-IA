#!/usr/bin/env bash
# Charge l'environnement de développement local.
#
#   source scripts/dev-env.sh
#
# Reprend les identifiants du .env pour la base, mais force l'hôte sur le
# conteneur local : le .env du projet contient le DATABASE_URL de production,
# et un poste de développement ne doit jamais s'y connecter.

set -a
[ -f .env ] && . ./.env
set +a

: "${DB_PORT_HOST:=5433}"

export DATABASE_URL="postgres://${DB_USER:-axel}:${DB_PASSWORD:-password123}@127.0.0.1:${DB_PORT_HOST}/${DB_NAME:-jobpilot_db}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/1}"
export CELERY_BROKER_URL="${CELERY_BROKER_URL:-$REDIS_URL}"
export CELERY_RESULT_BACKEND="${CELERY_RESULT_BACKEND:-$REDIS_URL}"
export ENVIRONMENT=development
export DEBUG=true

echo "Environnement de développement chargé."
echo "  Base   : 127.0.0.1:${DB_PORT_HOST}/${DB_NAME:-jobpilot_db}"
echo "  Redis  : ${REDIS_URL}"
