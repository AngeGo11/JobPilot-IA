#!/usr/bin/env bash
# Provisionne et configure l'infrastructure Azure manquante.
#
#   az login
#   ./scripts/azure-setup.sh                # affiche ce qui serait fait
#   ./scripts/azure-setup.sh --apply        # exécute
#
# Idempotent : relançable sans dégât. Chaque étape vérifie l'état existant
# avant d'agir.
set -euo pipefail

APPLY=false
[ "${1:-}" = "--apply" ] && APPLY=true

APP_NAME="${APP_NAME:-jobpilot-ai}"
PG_SERVER="${PG_SERVER:-jobpilot-ia-postgres}"
REDIS_NAME="${REDIS_NAME:-jobpilot-redis}"
GA_ID="${GA_ID:-G-FXM45CY9ZG}"

bleu()  { printf "\033[1;34m%s\033[0m\n" "$*"; }
vert()  { printf "\033[0;32m  %s\033[0m\n" "$*"; }
jaune() { printf "\033[0;33m  %s\033[0m\n" "$*"; }
rouge() { printf "\033[0;31m  %s\033[0m\n" "$*"; }

lancer() {
    if $APPLY; then
        "$@"
    else
        printf "    \033[2m[simulation] %s\033[0m\n" "$*"
    fi
}

# --------------------------------------------------------------------------- #
bleu "0. Découverte des ressources"

if ! az account show >/dev/null 2>&1; then
    rouge "Session Azure expirée. Lancez d'abord : az login"
    exit 1
fi
vert "Abonnement : $(az account show --query name -o tsv)"

RG=$(az webapp list --query "[?name=='$APP_NAME'].resourceGroup | [0]" -o tsv 2>/dev/null || true)
if [ -z "$RG" ]; then
    rouge "Application « $APP_NAME » introuvable. Ajustez APP_NAME."
    exit 1
fi
vert "Groupe de ressources : $RG"

REGION=$(az group show --name "$RG" --query location -o tsv)
vert "Région : $REGION"

PG_RG=$(az postgres flexible-server list --query "[?name=='$PG_SERVER'].resourceGroup | [0]" -o tsv 2>/dev/null || true)
[ -z "$PG_RG" ] && { rouge "Serveur PostgreSQL « $PG_SERVER » introuvable."; exit 1; }
vert "Serveur PostgreSQL : $PG_SERVER (groupe $PG_RG)"

INSTANCES=$(az webapp show --name "$APP_NAME" --resource-group "$RG" \
    --query "siteConfig.numberOfWorkers" -o tsv 2>/dev/null || echo 1)

# --------------------------------------------------------------------------- #
bleu "1. Extension PostgreSQL « vector » (obligatoire)"
# Sans elle, la migration matching.0010 échoue et le déploiement s'interrompt.

ACTUEL=$(az postgres flexible-server parameter show \
    --resource-group "$PG_RG" --server-name "$PG_SERVER" \
    --name azure.extensions --query value -o tsv 2>/dev/null || echo "")

if echo ",$ACTUEL," | grep -qi ",vector,"; then
    vert "déjà autorisée (valeur actuelle : ${ACTUEL:-vide})"
else
    # Ce paramètre REMPLACE la liste : on préserve les extensions déjà
    # autorisées, sinon on les désactive sans le voir.
    if [ -n "$ACTUEL" ]; then
        NOUVEAU="$ACTUEL,vector"
        jaune "extensions existantes préservées : $ACTUEL"
    else
        NOUVEAU="vector"
    fi
    jaune "autorisation de « vector » -> $NOUVEAU"
    lancer az postgres flexible-server parameter set \
        --resource-group "$PG_RG" --server-name "$PG_SERVER" \
        --name azure.extensions --value "$NOUVEAU" --output none
fi

# --------------------------------------------------------------------------- #
bleu "2. Cache Redis (broker Celery + cache partagé)"
# Coût : niveau Basic C0, de l'ordre de 15 à 20 EUR par mois.

if az redis show --name "$REDIS_NAME" --resource-group "$RG" >/dev/null 2>&1; then
    vert "« $REDIS_NAME » existe déjà"
else
    jaune "création de « $REDIS_NAME » (Basic C0, ~15-20 EUR/mois) — compter 15 à 20 min"
    lancer az redis create \
        --name "$REDIS_NAME" --resource-group "$RG" --location "$REGION" \
        --sku Basic --vm-size c0 --minimum-tls-version 1.2 --output none
fi

if $APPLY; then
    REDIS_HOST=$(az redis show --name "$REDIS_NAME" --resource-group "$RG" --query hostName -o tsv)
    REDIS_KEY=$(az redis list-keys --name "$REDIS_NAME" --resource-group "$RG" --query primaryKey -o tsv)
    # rediss:// + port 6380 : Azure Cache impose TLS.
    REDIS_CACHE="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/1"
    REDIS_BROKER="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"
    vert "hôte : $REDIS_HOST"
else
    REDIS_CACHE="rediss://:<cle>@<hote>:6380/1"
    REDIS_BROKER="rediss://:<cle>@<hote>:6380/0"
fi

# --------------------------------------------------------------------------- #
bleu "3. Variables d'application"

# ssl_cert_reqs=none : Azure Cache présente un certificat que redis-py ne peut
# pas valider par défaut faute de chaîne fournie dans l'image.
lancer az webapp config appsettings set \
    --name "$APP_NAME" --resource-group "$RG" --output none \
    --settings \
        "GA_MEASUREMENT_ID=$GA_ID" \
        "REDIS_URL=${REDIS_CACHE}?ssl_cert_reqs=none" \
        "CELERY_BROKER_URL=${REDIS_BROKER}?ssl_cert_reqs=none" \
        "CELERY_RESULT_BACKEND=${REDIS_BROKER}?ssl_cert_reqs=none" \
        "CELERY_CONCURRENCY=2" \
        "WEB_CONCURRENCY=4"
vert "GA_MEASUREMENT_ID, REDIS_URL, CELERY_* , WEB_CONCURRENCY"

# --------------------------------------------------------------------------- #
bleu "4. Commande de démarrage"

CMD_ACTUELLE=$(az webapp config show --name "$APP_NAME" --resource-group "$RG" \
    --query appCommandLine -o tsv 2>/dev/null || echo "")
if [ "$CMD_ACTUELLE" = "bash deploy/deploy.sh" ]; then
    vert "déjà « bash deploy/deploy.sh »"
else
    jaune "actuelle : ${CMD_ACTUELLE:-<vide>}  ->  bash deploy/deploy.sh"
    lancer az webapp config set --name "$APP_NAME" --resource-group "$RG" \
        --startup-file "bash deploy/deploy.sh" --output none
fi

# --------------------------------------------------------------------------- #
bleu "5. Contrôles"

if [ "${INSTANCES:-1}" -gt 1 ]; then
    rouge "Le plan tourne sur $INSTANCES instances."
    rouge "Le planificateur est intégré au worker (--beat) : chaque instance"
    rouge "déclencherait les tâches et les alertes partiraient en double."
    rouge "Ramenez à 1 instance, ou sortez beat dans son propre conteneur."
else
    vert "1 instance : planificateur intégré au worker, sans risque de doublon"
fi

echo
if $APPLY; then
    bleu "Terminé. Après le prochain déploiement, exécuter dans le SSH de l'app :"
    echo "    python manage.py reconcile_credits --fix"
    echo "    python manage.py backfill_embeddings --dry-run"
    echo "    python manage.py backfill_embeddings"
    echo
    jaune "Puis retirer les lignes de cron check_new_offers et cleanup_expired_alerts :"
    jaune "le planificateur Celery les prend en charge, elles feraient doublon."
else
    bleu "Simulation terminée. Relancer avec --apply pour exécuter."
fi
