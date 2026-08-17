#!/usr/bin/env bash
# Point d'entrée conservé à la racine pour compatibilité.
#
# La commande de démarrage configurée sur Azure App Service est
# « bash deploy.sh ». Déplacer le script dans deploy/ sans laisser ce relais
# casserait le démarrage au prochain déploiement, et la panne n'apparaîtrait
# qu'après la mise en ligne du nouvel artefact — donc trop tard.
#
# Le contenu réel vit dans deploy/deploy.sh.
exec bash "$(dirname "$0")/deploy/deploy.sh"
