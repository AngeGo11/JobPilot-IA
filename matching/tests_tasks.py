"""
Tests du traitement asynchrone (phase 2).

Les tests s'exécutent avec `CELERY_TASK_ALWAYS_EAGER` : la tâche tourne dans le
processus de test, ce qui vérifie le contrat métier (débit, remboursement,
autorisation, format de réponse) sans dépendre d'un broker.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from matching.models import AIJob, JobMatch, JobOffer
from matching.tasks import generate_cover_letter_task, optimize_cv_task
from matching.use_cases import AIOperation, InsufficientCredits
from resumes.models import Resume
from subscriptions.models import CreditEntry
from subscriptions.services.credits import grant
from utils.gemini_safe import GeminiServiceUnavailable

User = get_user_model()


class AsyncFixtureMixin:
    def build_fixture(self, credits=3):
        user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        user.ai_credits = 0
        user.save(update_fields=["ai_credits"])
        grant(user, credits, reason=CreditEntry.Reason.SIGNUP)

        resume = Resume.objects.create(
            user=user,
            title="CV Python",
            file="cvs/test.pdf",
            extracted_text="Python Django PostgreSQL Docker",
            detected_job_title="Développeur Python",
        )
        offer = JobOffer.objects.create(
            remote_id="FT-ASYNC-1",
            title="Développeur Python",
            company_name="ACME",
            description="Python Django équipe agile",
        )
        match = JobMatch.objects.create(
            resume=resume, user=user, job_offer=offer, score=88, is_unlocked=True
        )
        return user, resume, match


class EnqueueTests(AsyncFixtureMixin, TestCase):
    """Contrat de `AIOperation.enqueue`."""

    def setUp(self):
        self.user, self.resume, self.match = self.build_fixture()

    @patch("matching.services.ai_letter_generator.AILetterGenerator")
    def test_success_records_job_and_charges_once(self, generator_cls):
        generator_cls.return_value.generate_cover_letter.return_value = "Madame, Monsieur…"

        job = AIOperation("generate_letter").enqueue(
            self.user,
            generate_cover_letter_task,
            job_match=self.match,
            match_id=self.match.pk,
            resume_id=self.resume.pk,
            user_id=self.user.pk,
        )

        self.assertEqual(job.status, AIJob.Status.SUCCESS)
        self.assertEqual(job.result["letter"], "Madame, Monsieur…")
        self.assertEqual(job.user, self.user)
        self.assertIsNotNone(job.credit_entry)

        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 2)

    @patch("matching.services.ai_letter_generator.AILetterGenerator")
    def test_task_failure_refunds_the_credit(self, generator_cls):
        generator_cls.return_value.generate_cover_letter.side_effect = GeminiServiceUnavailable()

        job = AIOperation("generate_letter").enqueue(
            self.user,
            generate_cover_letter_task,
            job_match=self.match,
            match_id=self.match.pk,
            resume_id=self.resume.pk,
            user_id=self.user.pk,
        )

        self.assertEqual(job.status, AIJob.Status.FAILURE)
        self.assertEqual(job.error_status, 503)

        # Le crédit débité à l'enfilement doit être rendu par la tâche.
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 3)
        self.assertTrue(job.credit_entry.reversals.exists())

    def test_empty_balance_is_refused_before_enqueuing(self):
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])

        with self.assertRaises(InsufficientCredits):
            AIOperation("generate_letter").enqueue(
                self.user,
                generate_cover_letter_task,
                match_id=self.match.pk,
                resume_id=self.resume.pk,
                user_id=self.user.pk,
            )

        # Aucune tâche ne doit avoir été créée pour un solde vide.
        self.assertEqual(AIJob.objects.count(), 0)

    @patch("matching.tasks.generate_cover_letter_task.apply_async")
    def test_broker_down_refunds_and_leaves_no_orphan_job(self, apply_async):
        from matching.use_cases import AIOperationError

        apply_async.side_effect = OSError("broker injoignable")

        with self.assertRaises(AIOperationError) as ctx:
            AIOperation("generate_letter").enqueue(
                self.user,
                generate_cover_letter_task,
                match_id=self.match.pk,
                resume_id=self.resume.pk,
                user_id=self.user.pk,
            )

        self.assertEqual(ctx.exception.status, 503)
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 3)
        self.assertEqual(AIJob.objects.count(), 0)


class JobStatusEndpointTests(AsyncFixtureMixin, TestCase):
    """Le point d'entrée de suivi ne doit rien laisser fuir."""

    def setUp(self):
        self.user, self.resume, self.match = self.build_fixture()
        self.job = AIJob.objects.create(
            task_id="tache-de-test-1",
            user=self.user,
            operation="generate_letter",
            status=AIJob.Status.SUCCESS,
            result={"letter": "Contenu confidentiel du candidat"},
        )
        self.url = reverse("ai_job_status", kwargs={"task_id": self.job.task_id})

    def test_owner_gets_the_result(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["refined_letter"], "Contenu confidentiel du candidat")

    def test_another_user_gets_404(self):
        """
        Le contrôle porte sur le propriétaire, pas sur la difficulté à deviner
        l'identifiant : sans ce filtre, connaître un identifiant suffirait à
        lire la lettre d'un autre candidat.
        """
        intruder = User.objects.create_user(email="autre@example.com", password="MotDePasse!2024")
        self.client.force_login(intruder)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Contenu confidentiel", response.content.decode())

    def test_anonymous_is_redirected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_pending_job_reports_progress(self):
        pending = AIJob.objects.create(
            task_id="tache-en-cours",
            user=self.user,
            operation="optimize_cv",
            status=AIJob.Status.RUNNING,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("ai_job_status", kwargs={"task_id": pending.task_id})
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["pending"])
        self.assertNotIn("refined_letter", payload)

    def test_failed_job_reports_its_status_code(self):
        failed = AIJob.objects.create(
            task_id="tache-en-echec",
            user=self.user,
            operation="optimize_cv",
            status=AIJob.Status.FAILURE,
            error="Service indisponible",
            error_status=429,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("ai_job_status", kwargs={"task_id": failed.task_id})
        )

        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.json()["success"])


class ViewIntegrationTests(AsyncFixtureMixin, TestCase):
    """Les vues doivent répondre sans attendre la fin du traitement."""

    def setUp(self):
        self.user, self.resume, self.match = self.build_fixture()
        self.client.force_login(self.user)

    @patch("resumes.services.ai_optimizer.AIOptimizer")
    def test_optimize_cv_returns_a_pollable_job(self, optimizer_cls):
        optimizer_cls.return_value.optimize_for_offer.return_value = {"score": 82}

        response = self.client.post(
            reverse("optimize_cv", kwargs={"match_id": self.match.pk})
        )
        payload = response.json()

        self.assertIn(response.status_code, (200, 202))
        self.assertIn("task_id", payload)
        self.assertIn("poll_url", payload)
        # L'identifiant renvoyé doit être interrogeable par son propriétaire.
        self.assertEqual(self.client.get(payload["poll_url"]).status_code, 200)

    def test_no_credit_returns_402_without_creating_a_job(self):
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])

        response = self.client.post(
            reverse("optimize_cv", kwargs={"match_id": self.match.pk})
        )

        self.assertEqual(response.status_code, 402)
        self.assertEqual(AIJob.objects.count(), 0)


class PurgeTests(TestCase):
    def test_purge_removes_only_old_finished_jobs(self):
        from datetime import timedelta

        from django.utils import timezone

        from matching.tasks import purge_finished_jobs_task

        user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        old = AIJob.objects.create(
            task_id="ancienne", user=user, operation="op",
            status=AIJob.Status.SUCCESS, finished_at=timezone.now() - timedelta(days=30),
        )
        recent = AIJob.objects.create(
            task_id="recente", user=user, operation="op",
            status=AIJob.Status.SUCCESS, finished_at=timezone.now(),
        )
        running = AIJob.objects.create(
            task_id="en-cours", user=user, operation="op", status=AIJob.Status.RUNNING
        )

        purge_finished_jobs_task(days=7)

        self.assertFalse(AIJob.objects.filter(pk=old.pk).exists())
        self.assertTrue(AIJob.objects.filter(pk=recent.pk).exists())
        self.assertTrue(AIJob.objects.filter(pk=running.pk).exists())
