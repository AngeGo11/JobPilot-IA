"""
Contrôles de santé des dépendances externes.

Chaque contrôle renvoie un dict {key, label, status, detail} où `status` vaut
"ok", "warn" ou "error". Aucun contrôle ne doit lever : une dépendance HS ne
doit pas rendre la page de supervision inaccessible.
"""
import logging
import os
import shutil
import socket
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from administration.models import TaskRun

logger = logging.getLogger(__name__)

OK, WARN, ERROR = "ok", "warn", "error"

# Tâches planifiées attendues, avec l'intervalle maximum toléré entre deux
# exécutions avant de considérer que le cron est cassé.
EXPECTED_TASKS = {
    "check_new_offers": timedelta(hours=12),
    "cleanup_expired_alerts": timedelta(days=2),
}


def _check(key, label, fn):
    try:
        status, detail = fn()
    except Exception as exc:  # noqa: BLE001 - on veut vraiment tout attraper
        logger.warning("Contrôle de santé « %s » en échec : %s", key, exc)
        status, detail = ERROR, str(exc)[:200]
    return {"key": key, "label": label, "status": status, "detail": detail}


def _database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    engine = connection.settings_dict["ENGINE"].rsplit(".", 1)[-1]
    return OK, f"{engine} – {connection.settings_dict.get('NAME', '')}"


def _cache_backend():
    probe_key = "administration:health:probe"
    cache.set(probe_key, "1", 10)
    if cache.get(probe_key) != "1":
        return ERROR, "Écriture/lecture du cache impossible"
    backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]
    if backend == "LocMemCache":
        return WARN, "LocMemCache : cache non partagé entre processus"
    return OK, backend


def _stripe():
    missing = [
        name for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")
        if not getattr(settings, name, None)
    ]
    if missing:
        return ERROR, "Clés manquantes : " + ", ".join(missing)
    key = settings.STRIPE_SECRET_KEY
    mode = "test" if key.startswith(("sk_test", "rk_test")) else "live"
    prices = [
        name for name in
        ("STRIPE_PRICE_PASS24H", "STRIPE_PRICE_SPRINT", "STRIPE_PRICE_PRO", "STRIPE_PRICE_PACK")
        if not getattr(settings, name, None)
    ]
    if prices:
        return WARN, f"Mode {mode} – tarifs non configurés : " + ", ".join(prices)
    if mode == "test" and not settings.DEBUG:
        return WARN, "Clé de test utilisée hors développement"
    return OK, f"Configuré – mode {mode}"


def _email():
    backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
    # Tout backend non SMTP n'envoie rien : inutile — et coûteux — d'ouvrir une
    # socket vers le serveur de messagerie. Sans cette sortie anticipée, la
    # suite de tests attendait 3 s de timeout à chaque appel du contrôle.
    if backend != "EmailBackend" or "smtp" not in settings.EMAIL_BACKEND:
        return WARN, f"{backend} : aucun email réellement envoyé"
    host = getattr(settings, "EMAIL_HOST", None)
    if not host or not getattr(settings, "EMAIL_HOST_USER", None):
        return ERROR, "EMAIL_HOST / EMAIL_HOST_USER non renseignés"
    port = int(getattr(settings, "EMAIL_PORT", 587) or 587)
    try:
        # Simple test de joignabilité TCP : pas d'authentification, pas d'envoi.
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError as exc:
        return ERROR, f"{host}:{port} injoignable ({exc.strerror or exc})"
    return OK, f"{host}:{port} joignable"


def _france_travail():
    if not getattr(settings, "CLIENT_ID", None) or not getattr(settings, "CLIENT_SECRET_KEY", None):
        return ERROR, "ID_CLIENT / CLIENT_SECRET non renseignés"
    if not getattr(settings, "API_URL", None):
        return WARN, "API_BASE_URL non renseignée"
    return OK, "Identifiants API présents"


def _storage():
    if os.getenv("AZURE_ACCOUNT_NAME"):
        container = os.getenv("AZURE_CONTAINER", "media")
        if not os.getenv("AZURE_ACCOUNT_KEY"):
            return ERROR, "AZURE_ACCOUNT_KEY manquante"
        return OK, f"Azure Blob – conteneur « {container} »"

    path = settings.MEDIA_ROOT
    if not os.path.isdir(path):
        return WARN, f"{path} n'existe pas encore"
    usage = shutil.disk_usage(path)
    free_pct = usage.free * 100 / usage.total
    detail = f"Disque local – {free_pct:.0f} % libre ({usage.free / 1024**3:.1f} Go)"
    if free_pct < 5:
        return ERROR, detail
    if free_pct < 15:
        return WARN, detail
    return OK, detail


def _security():
    """Vérifie les réglages sensibles en production."""
    issues = []
    if settings.DEBUG:
        issues.append("DEBUG=True")
    if "*" in settings.ALLOWED_HOSTS:
        issues.append("ALLOWED_HOSTS='*'")
    if not settings.SECRET_KEY or len(settings.SECRET_KEY) < 40:
        issues.append("SECRET_KEY faible")
    env = os.getenv("ENVIRONMENT", "development")
    if env == "production" and issues:
        return ERROR, "En production : " + ", ".join(issues)
    if issues:
        return WARN, f"Environnement « {env} » : " + ", ".join(issues)
    return OK, f"Environnement « {env} » conforme"


def _scheduled_tasks():
    """Compare la dernière exécution de chaque tâche à sa fréquence attendue."""
    now = timezone.now()
    problems = []
    for name, max_gap in EXPECTED_TASKS.items():
        last = (
            TaskRun.objects.filter(name=name, status=TaskRun.Status.SUCCESS)
            .order_by("-started_at")
            .first()
        )
        if last is None:
            problems.append(f"{name} : jamais exécutée")
        elif now - last.started_at > max_gap:
            problems.append(f"{name} : dernière exécution il y a {(now - last.started_at).days} j")
    if not problems:
        return OK, f"{len(EXPECTED_TASKS)} tâche(s) planifiée(s) à jour"
    return WARN, " ; ".join(problems)


CHECKS = (
    ("database", "Base de données", _database),
    ("cache", "Cache", _cache_backend),
    ("stripe", "Paiements Stripe", _stripe),
    ("email", "Envoi d'emails", _email),
    ("france_travail", "API France Travail", _france_travail),
    ("storage", "Stockage des CV", _storage),
    ("security", "Configuration sécurité", _security),
    ("tasks", "Tâches planifiées", _scheduled_tasks),
)


def run_all():
    """Exécute tous les contrôles et retourne (résultats, statut global)."""
    results = [_check(key, label, fn) for key, label, fn in CHECKS]
    statuses = {r["status"] for r in results}
    if ERROR in statuses:
        overall = ERROR
    elif WARN in statuses:
        overall = WARN
    else:
        overall = OK
    return results, overall
