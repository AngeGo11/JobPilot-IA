"""
Point d'entrée Celery.

Découvre automatiquement les modules `tasks.py` de chaque app installée.
Lancement d'un worker :

    celery -A JobPilot worker --loglevel=info
    celery -A JobPilot beat --loglevel=info      # tâches planifiées
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "JobPilot.settings")

app = Celery("jobpilot")

# Toute la configuration vit dans settings.py, préfixée CELERY_.
app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

# Tâches planifiées. Remplace le cron à configurer à la main sur l'hébergeur :
# la planification est versionnée avec le code, et chaque exécution laisse une
# trace dans `TaskRun` visible depuis la supervision du back-office.
app.conf.beat_schedule = {
    "verifier-nouvelles-offres": {
        "task": "matching.tasks.check_new_offers_task",
        "schedule": crontab(minute=0, hour="*/6"),  # toutes les 6 heures
    },
    "purger-erreurs": {
        "task": "matching.tasks.purge_error_logs_task",
        "schedule": crontab(minute=15, hour=4),  # chaque nuit à 4 h 15
    },
    "nettoyer-alertes-expirees": {
        "task": "matching.tasks.cleanup_expired_alerts_task",
        "schedule": crontab(minute=30, hour=3),  # chaque nuit à 3 h 30
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):  # pragma: no cover - utilitaire de diagnostic
    print(f"Requête reçue : {self.request!r}")
