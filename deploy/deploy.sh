#!/usr/bin/env bash
# Démarrage en production (Azure App Service).
set -euo pipefail

python3 manage.py collectstatic --noinput
python3 manage.py migrate --noinput

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
