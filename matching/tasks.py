"""
Tâches de fond du domaine matching.

Tout ce qui appelle un service externe ou dure plus d'une seconde vit ici, pas
dans une vue. Le worker Celery absorbe la latence réseau et les temporisations
de `gemini_safe` : les `time.sleep()` du backoff n'immobilisent plus un worker
web, et une génération lente n'empêche plus les autres visiteurs de naviguer.

Contrat commun à toutes les tâches facturées :
  - le débit du crédit a lieu **dans la requête web**, pour que l'utilisateur
    soit prévenu immédiatement s'il n'a plus de solde ;
  - la tâche reçoit l'identifiant de l'écriture et la rembourse elle-même en
    cas d'échec, quel qu'il soit.
"""
import logging
from contextlib import contextmanager

from celery import shared_task
from django.utils import timezone

from administration.services.tasks import track_run
from matching.models import AIJob, JobMatch
from resumes.models import Resume
from subscriptions.models import CreditEntry
from subscriptions.services.credits import refund
from utils.gemini_safe import FairUseExceeded, GeminiServiceUnavailable

logger = logging.getLogger(__name__)

# Correspondance entre une exception de service et ce que l'interface doit
# afficher. Identique à celle de `use_cases.AIOperation`, pour que le mode
# synchrone et le mode asynchrone se comportent de la même façon.
ERROR_MAPPING = {
    FairUseExceeded: (
        429,
        "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). "
        "Ne vous inquiétez pas, AUCUN crédit n'a été décompté.",
    ),
    GeminiServiceUnavailable: (
        503,
        "Notre assistant IA est momentanément très sollicité. Ne vous inquiétez "
        "pas, AUCUN crédit n'a été décompté. Veuillez réessayer dans quelques instants.",
    ),
    ValueError: (400, None),  # message repris de l'exception
}

DEFAULT_ERROR = (
    503,
    "Notre assistant IA est momentanément très sollicité. Ne vous inquiétez "
    "pas, AUCUN crédit n'a été décompté. Veuillez réessayer dans quelques instants.",
)


def _classify(exc):
    for exc_type, (status, message) in ERROR_MAPPING.items():
        if isinstance(exc, exc_type):
            if message is None:
                return status, f"Erreur de validation : {exc}. Aucun crédit n'a été décompté."
            return status, message
    return DEFAULT_ERROR


@contextmanager
def _tracked_job(task_id):
    """
    Encadre l'exécution d'une tâche facturée.

    Met à jour l'état du `AIJob` et garantit le remboursement du crédit associé
    si quoi que ce soit échoue — y compris une erreur qui n'a pas été prévue.
    """
    job = AIJob.objects.filter(task_id=task_id).select_related("credit_entry").first()
    if job is None:
        # Peut arriver si la tâche est rejouée après purge de la base ; on
        # laisse alors l'exécution se poursuivre sans suivi plutôt que d'échouer.
        logger.warning("Aucun AIJob pour la tâche %s", task_id)
        yield None
        return

    job.status = AIJob.Status.RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])

    try:
        yield job
    except Exception as exc:
        status, message = _classify(exc)
        if job.credit_entry_id:
            entry = CreditEntry.objects.filter(pk=job.credit_entry_id).first()
            if entry is not None:
                refund(entry, note=f"Échec de la tâche : {type(exc).__name__}")
        job.status = AIJob.Status.FAILURE
        job.error = message
        job.error_status = status
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "error_status", "finished_at"])
        logger.exception("Échec de la tâche %s (%s)", job.operation, task_id)
        # On n'ajoute pas de `retry` : l'utilisateur a déjà été remboursé et
        # attend une réponse. Il relance lui-même s'il le souhaite.
        return
    else:
        job.status = AIJob.Status.SUCCESS
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "result", "finished_at"])


# --------------------------------------------------------------------------- #
# Tâches facturées
# --------------------------------------------------------------------------- #

@shared_task(bind=True, name="matching.tasks.generate_cover_letter_task")
def generate_cover_letter_task(self, *, match_id, resume_id, user_id):
    """Génère une lettre de motivation et la range dans le résultat du job."""
    from matching.services.ai_letter_generator import AILetterGenerator

    with _tracked_job(self.request.id) as job:
        match = JobMatch.objects.select_related("job_offer").get(pk=match_id)
        resume = Resume.objects.get(pk=resume_id)

        letter = AILetterGenerator().generate_cover_letter(
            resume=resume,
            job_match=match,
            tone="professional",
            user_id=user_id,
        )
        if job is not None:
            job.result = {"letter": letter}
        return letter


@shared_task(bind=True, name="matching.tasks.refine_cover_letter_task")
def refine_cover_letter_task(self, *, match_id, current_text, instructions, improvement_type, user_id):
    """Améliore une lettre existante et la sauvegarde sur la candidature."""
    from matching.services.ai_letter_generator import AILetterGenerator

    with _tracked_job(self.request.id) as job:
        generator = AILetterGenerator()
        final_instructions = generator._build_refinement_instructions(
            instructions, improvement_type
        )
        refined = generator.refine_cover_letter(
            current_text, final_instructions, user_id=user_id
        )

        JobMatch.objects.filter(pk=match_id).update(cover_letter_content=refined)
        if job is not None:
            job.result = {"letter": refined}
        return refined


@shared_task(bind=True, name="matching.tasks.optimize_cv_task")
def optimize_cv_task(self, *, match_id, resume_id, user_id):
    """Produit les suggestions d'adaptation du CV à une offre."""
    from resumes.services.ai_optimizer import AIOptimizer

    with _tracked_job(self.request.id) as job:
        match = JobMatch.objects.select_related("job_offer").get(pk=match_id)
        resume = Resume.objects.get(pk=resume_id)
        offer = match.job_offer

        suggestions = AIOptimizer().optimize_for_offer(
            cv_text=resume.extracted_text,
            job_description=offer.description or "",
            job_title=offer.title or "",
            user_id=user_id,
        )
        if job is not None:
            job.result = {"suggestions": suggestions}
        return suggestions


# --------------------------------------------------------------------------- #
# Tâches planifiées
# --------------------------------------------------------------------------- #

@shared_task(name="matching.tasks.check_new_offers_task")
def check_new_offers_task():
    """
    Équivalent planifié de `manage.py check_new_offers`.

    Remplace la ligne de cron à configurer sur l'hébergeur : la planification
    est versionnée dans `JobPilot/celery.py`, et `TaskRun` reste alimenté pour
    la page de supervision.
    """
    from django.core.management import call_command

    call_command("check_new_offers")


@shared_task(name="matching.tasks.cleanup_expired_alerts_task")
def cleanup_expired_alerts_task():
    from django.core.management import call_command

    call_command("cleanup_expired_alerts")


@shared_task(name="matching.tasks.purge_finished_jobs_task")
def purge_finished_jobs_task(days=7):
    """
    Supprime les traitements terminés depuis plus de `days` jours.

    Sans purge, `AIJob` grossit indéfiniment alors que son intérêt est de
    l'ordre de la minute pour l'utilisateur, et de quelques jours pour la
    supervision.
    """
    from datetime import timedelta

    with track_run("purge_finished_jobs") as run:
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = AIJob.objects.filter(
            status__in=[AIJob.Status.SUCCESS, AIJob.Status.FAILURE],
            finished_at__lt=cutoff,
        ).delete()
        run.items_processed = deleted


# --------------------------------------------------------------------------- #
# Vectorisation (phase 4 — matching sémantique)
# --------------------------------------------------------------------------- #

@shared_task(name="matching.tasks.embed_resume_task")
def embed_resume_task(resume_id):
    """
    Calcule et stocke le vecteur d'un CV.

    Déclenchée après l'analyse IA du CV. Ne consomme pas de crédit : c'est un
    coût d'infrastructure, pas une action demandée par l'utilisateur.
    """
    from django.utils import timezone as tz

    from matching.services import embeddings as emb

    resume = Resume.objects.filter(pk=resume_id).first()
    if resume is None:
        return

    text = emb.resume_text(resume)
    fingerprint = emb.content_fingerprint(text)
    if resume.embedding is not None and resume.embedding_fingerprint == fingerprint:
        return  # contenu inchangé, rien à recalculer

    try:
        vector = emb.embed(text, user_id=resume.user_id, task_type="RETRIEVAL_QUERY")
    except emb.EmbeddingUnavailable as exc:
        logger.warning("Vectorisation du CV %s impossible : %s", resume_id, exc)
        return

    Resume.objects.filter(pk=resume_id).update(
        embedding=vector, embedding_fingerprint=fingerprint, embedded_at=tz.now()
    )
    rescore_resume_matches_task.delay(resume_id)


@shared_task(name="matching.tasks.embed_offers_task")
def embed_offers_task(offer_ids=None, limit=200):
    """
    Vectorise les offres qui ne le sont pas encore.

    Sans `offer_ids`, traite les plus récentes d'abord : ce sont celles qui
    seront proposées aux candidats.
    """
    from django.utils import timezone as tz

    from matching.models import JobOffer
    from matching.services import embeddings as emb

    with track_run("embed_offers") as run:
        queryset = JobOffer.objects.all()
        if offer_ids:
            queryset = queryset.filter(pk__in=offer_ids)
        else:
            queryset = queryset.filter(embedding__isnull=True)
        queryset = queryset.order_by("-created_at")[:limit]

        done = 0
        for offer in queryset:
            text = emb.offer_text(offer)
            fingerprint = emb.content_fingerprint(text)
            if offer.embedding is not None and offer.embedding_fingerprint == fingerprint:
                continue
            try:
                vector = emb.embed(text, task_type="RETRIEVAL_DOCUMENT")
            except emb.EmbeddingUnavailable as exc:
                # Une offre illisible ne doit pas interrompre le lot : les
                # suivantes sont peut-être parfaitement valides.
                logger.warning("Vectorisation de l'offre %s impossible : %s", offer.pk, exc)
                continue
            JobOffer.objects.filter(pk=offer.pk).update(
                embedding=vector, embedding_fingerprint=fingerprint, embedded_at=tz.now()
            )
            done += 1

        run.items_processed = done
        return done


@shared_task(name="matching.tasks.rescore_resume_matches_task")
def rescore_resume_matches_task(resume_id):
    """
    Recalcule le score sémantique des correspondances d'un CV.

    Appelée après la vectorisation du CV ou d'un lot d'offres. Le score par
    mots-clés n'est pas touché : les deux cohabitent pendant la comparaison.
    """
    from matching.services.scoring import semantic_score

    resume = Resume.objects.filter(pk=resume_id).first()
    if resume is None or resume.embedding is None:
        return 0

    matches = (
        JobMatch.objects.filter(resume_id=resume_id)
        .select_related("job_offer")
        .exclude(job_offer__embedding__isnull=True)
    )

    updated = []
    for match in matches:
        score = semantic_score(resume, match.job_offer)
        if score is not None and score != match.semantic_score:
            match.semantic_score = score
            updated.append(match)

    if updated:
        JobMatch.objects.bulk_update(updated, ["semantic_score"], batch_size=500)
    return len(updated)


@shared_task(name="matching.tasks.embed_pending_task")
def embed_pending_task():
    """
    Rattrapage planifié : vectorise ce qui ne l'est pas encore.

    Filet de sécurité pour les CV et offres dont la vectorisation a échoué
    (quota Gemini atteint, service momentanément indisponible).
    """
    from matching.models import JobOffer

    with track_run("embed_pending") as run:
        offers = embed_offers_task(limit=200)

        pending_resumes = list(
            Resume.objects.filter(embedding__isnull=True)
            .exclude(extracted_text="")
            .values_list("pk", flat=True)[:50]
        )
        for resume_id in pending_resumes:
            embed_resume_task(resume_id)

        run.items_processed = offers + len(pending_resumes)
        logger.info(
            "Rattrapage : %s offre(s), %s CV. Restant : %s offre(s).",
            offers, len(pending_resumes),
            JobOffer.objects.filter(embedding__isnull=True).count(),
        )
