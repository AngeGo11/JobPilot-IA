"""
Enregistrement des exécutions de tâches planifiées.

À utiliser dans les commandes `manage.py` :

    from administration.services.tasks import track_run

    with track_run("check_new_offers") as run:
        ...
        run.items_processed = nb_alertes_traitees
"""
import logging
from contextlib import contextmanager

from django.utils import timezone

from administration.models import TaskRun

logger = logging.getLogger(__name__)

# Nombre d'exécutions conservées par tâche (purge automatique en fin de run).
KEEP_RUNS_PER_TASK = 50


@contextmanager
def track_run(name):
    """
    Crée une trace `TaskRun`, la marque en succès ou en échec à la sortie,
    puis relaie l'exception éventuelle à l'appelant.
    """
    run = TaskRun.objects.create(name=name, status=TaskRun.Status.RUNNING)
    try:
        yield run
    except Exception as exc:
        run.status = TaskRun.Status.ERROR
        run.message = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    else:
        run.status = TaskRun.Status.SUCCESS
    finally:
        run.finished_at = timezone.now()
        try:
            run.save(update_fields=["status", "message", "finished_at", "items_processed"])
            _purge(name)
        except Exception:  # pragma: no cover - ne jamais masquer l'erreur métier
            logger.exception("Impossible d'enregistrer la trace de la tâche %s", name)


def _purge(name):
    """Garde les KEEP_RUNS_PER_TASK exécutions les plus récentes."""
    ids = list(
        TaskRun.objects.filter(name=name)
        .order_by("-started_at")
        .values_list("id", flat=True)[KEEP_RUNS_PER_TASK:]
    )
    if ids:
        TaskRun.objects.filter(id__in=ids).delete()
