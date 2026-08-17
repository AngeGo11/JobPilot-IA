#!/usr/bin/env bash
# Démarrage en production (Azure App Service).
#
# App Service n'exécute qu'un processus par application. Le worker Celery est
# donc lancé en arrière-plan dans le même conteneur, plutôt que dans une
# seconde application : un processus qui n'écoute aucun port est jugé en
# mauvaise santé par App Service et redémarré en boucle.
#
# Contrepartie assumée : web et worker partagent CPU et mémoire du plan, et un
# redémarrage les arrête tous les deux. À la volumétrie actuelle c'est tenable ;
# le jour où ça ne l'est plus, la bonne réponse est Azure Container Apps.
set -euo pipefail

python3 manage.py collectstatic --noinput
python3 manage.py migrate --noinput

# --- Worker Celery ---------------------------------------------------------
# Lancé seulement si un broker est configuré. Sans CELERY_BROKER_URL,
# l'application retombe sur l'exécution synchrone (CELERY_TASK_ALWAYS_EAGER)
# et démarrer un worker ne servirait à rien.
#
# -B embarque le planificateur (Celery Beat) dans le worker. Cela suppose UNE
# SEULE instance : si le plan App Service est mis à l'échelle au-delà, chaque
# instance déclencherait les tâches planifiées et les alertes partiraient en
# double. Dans ce cas, sortir beat dans son propre conteneur.
if [ -n "${CELERY_BROKER_URL:-}" ]; then
    echo "Démarrage du worker Celery (avec planificateur intégré)…"
    celery -A JobPilot worker \
        --beat \
        --loglevel=info \
        --concurrency="${CELERY_CONCURRENCY:-2}" \
        --max-tasks-per-child=50 &
else
    echo "CELERY_BROKER_URL absente : traitements exécutés dans la requête web."
fi

# --- Serveur web -----------------------------------------------------------
# --workers : sans cette option, gunicorn démarre UN worker synchrone et le
#   site ne sert qu'une requête à la fois. WEB_CONCURRENCY permet d'ajuster
#   depuis les variables d'application Azure sans modifier ce fichier.
# --timeout 60 : l'ancienne valeur de 600 s masquait des appels IA bloquants
#   dans le cycle requête/réponse. Un timeout court fait ressortir le problème
#   au lieu de l'absorber.
exec gunicorn JobPilot.wsgi:application \
    --bind=0.0.0.0:8000 \
    --workers="${WEB_CONCURRENCY:-4}" \
    --threads=2 \
    --timeout=60 \
    --graceful-timeout=30 \
    --access-logfile=- \
    --error-logfile=-
