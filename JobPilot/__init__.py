"""
Charge l'application Celery au démarrage de Django.

Sans cet import, le décorateur `@shared_task` ne trouve pas d'application
configurée et les tâches ne sont jamais enregistrées.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
