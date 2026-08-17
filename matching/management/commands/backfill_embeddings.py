"""
Vectorise le contenu existant et recalcule les scores sémantiques.

À lancer une fois après la mise en place du matching sémantique : les CV et les
offres déjà en base n'ont pas de vecteur, et le score sémantique reste donc nul
tant que ce rattrapage n'a pas tourné.

    python manage.py backfill_embeddings --dry-run     # estimation du coût
    python manage.py backfill_embeddings --limit 500
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from administration.services.tasks import track_run
from matching.models import JobMatch, JobOffer
from matching.services import embeddings as emb
from matching.services.scoring import semantic_score
from resumes.models import Resume


class Command(BaseCommand):
    help = "Calcule les vecteurs manquants des CV et des offres, puis recalcule les scores."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500, help="Nombre maximum d'éléments par catégorie.")
        parser.add_argument("--dry-run", action="store_true", help="Compte le travail à faire sans appeler l'API.")
        parser.add_argument("--offers-only", action="store_true")
        parser.add_argument("--resumes-only", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        dry_run = options["dry_run"]
        do_offers = not options["resumes_only"]
        do_resumes = not options["offers_only"]

        pending_offers = JobOffer.objects.filter(embedding__isnull=True).count()
        pending_resumes = (
            Resume.objects.filter(embedding__isnull=True).exclude(extracted_text="").count()
        )

        self.stdout.write(f"Offres sans vecteur : {pending_offers}")
        self.stdout.write(f"CV sans vecteur     : {pending_resumes}")

        if dry_run:
            total = (pending_offers if do_offers else 0) + (pending_resumes if do_resumes else 0)
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"Mode simulation : {total} appel(s) d'embedding seraient nécessaires. "
                "Chaque appel consomme le quota Gemini partagé avec les générations de lettres."
            ))
            return

        with track_run("backfill_embeddings") as run:
            processed = 0

            if do_offers:
                processed += self._embed_offers(limit)
            if do_resumes:
                processed += self._embed_resumes(limit)

            rescored = self._rescore()
            run.items_processed = processed

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{processed} vecteur(s) calculé(s), {rescored} score(s) sémantique(s) mis à jour."
        ))

    def _embed_offers(self, limit):
        queryset = JobOffer.objects.filter(embedding__isnull=True).order_by("-created_at")[:limit]
        done = 0
        for offer in queryset:
            text = emb.offer_text(offer)
            try:
                vector = emb.embed(text, task_type="RETRIEVAL_DOCUMENT")
            except emb.EmbeddingUnavailable as exc:
                self.stderr.write(self.style.WARNING(f"  offre {offer.pk} ignorée : {exc}"))
                continue
            JobOffer.objects.filter(pk=offer.pk).update(
                embedding=vector,
                embedding_fingerprint=emb.content_fingerprint(text),
                embedded_at=timezone.now(),
            )
            done += 1
            if done % 25 == 0:
                self.stdout.write(f"  {done} offre(s) vectorisée(s)…")
        return done

    def _embed_resumes(self, limit):
        queryset = (
            Resume.objects.filter(embedding__isnull=True)
            .exclude(extracted_text="")
            .order_by("-uploaded_at")[:limit]
        )
        done = 0
        for resume in queryset:
            text = emb.resume_text(resume)
            try:
                vector = emb.embed(text, user_id=resume.user_id, task_type="RETRIEVAL_QUERY")
            except emb.EmbeddingUnavailable as exc:
                self.stderr.write(self.style.WARNING(f"  CV {resume.pk} ignoré : {exc}"))
                continue
            Resume.objects.filter(pk=resume.pk).update(
                embedding=vector,
                embedding_fingerprint=emb.content_fingerprint(text),
                embedded_at=timezone.now(),
            )
            done += 1
            if done % 25 == 0:
                self.stdout.write(f"  {done} CV vectorisé(s)…")
        return done

    def _rescore(self):
        """Recalcule le score sémantique là où les deux vecteurs existent."""
        matches = (
            JobMatch.objects.select_related("resume", "job_offer")
            .exclude(resume__embedding__isnull=True)
            .exclude(job_offer__embedding__isnull=True)
        )
        updated = []
        for match in matches.iterator(chunk_size=500):
            score = semantic_score(match.resume, match.job_offer)
            if score is not None and score != match.semantic_score:
                match.semantic_score = score
                updated.append(match)
            if len(updated) >= 500:
                JobMatch.objects.bulk_update(updated, ["semantic_score"], batch_size=500)
                updated = []
        if updated:
            JobMatch.objects.bulk_update(updated, ["semantic_score"], batch_size=500)
        return matches.count()
