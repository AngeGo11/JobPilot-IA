"""
Tests des vues de matching qui touchent à la facturation ou à la propriété
des données.

`unlock_jobs` était le chemin le moins couvert alors que c'est celui qui
consomme un crédit — l'unité facturée du produit. Les contrôles de propriété
n'étaient pas testés non plus : une erreur là expose les candidatures d'un
candidat à un autre.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from matching.models import JobMatch, JobOffer
from resumes.models import Resume
from subscriptions.models import CreditEntry
from subscriptions.services.credits import grant, ledger_balance

User = get_user_model()


class MatchingFixtureMixin:
    def build(self, credits=3, verrouillees=3):
        user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        user.ai_credits = 0
        user.save(update_fields=["ai_credits"])
        if credits:
            grant(user, credits, reason=CreditEntry.Reason.SIGNUP)

        resume = Resume.objects.create(
            user=user, title="CV", file="cvs/a.pdf",
            detected_job_title="Développeur Python",
            extracted_text="python django",
        )
        matches = []
        for index in range(verrouillees):
            offre = JobOffer.objects.create(remote_id=f"FT-{index}", title=f"Poste {index}")
            matches.append(JobMatch.objects.create(
                resume=resume, user=user, job_offer=offre, score=80, is_unlocked=False
            ))
        return user, resume, matches


class UnlockJobsTests(MatchingFixtureMixin, TestCase):
    """Le déblocage consomme exactement un crédit, quel que soit le nombre d'offres."""

    def setUp(self):
        self.user, self.resume, self.matches = self.build()
        self.client.force_login(self.user)
        self.url = reverse("unlock_jobs", kwargs={"resume_id": self.resume.pk})

    def _solde(self):
        self.user.refresh_from_db()
        return self.user.ai_credits

    def test_unlocks_every_pending_offer_for_one_credit(self):
        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(
            JobMatch.objects.filter(resume=self.resume, is_unlocked=True).count(), 3
        )
        self.assertEqual(self._solde(), 2, "un seul crédit pour le lot")

    def test_debit_is_recorded_in_the_ledger(self):
        self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        ecriture = CreditEntry.objects.filter(reason=CreditEntry.Reason.CONSUMPTION).first()
        self.assertIsNotNone(ecriture, "le déblocage doit laisser une trace")
        self.assertEqual(ecriture.delta, -1)
        self.assertEqual(ledger_balance(self.user), 2)

    def test_empty_balance_returns_402_and_unlocks_nothing(self):
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])

        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 402)
        self.assertIn("pricing", response.json()["redirect"])
        self.assertEqual(JobMatch.objects.filter(is_unlocked=True).count(), 0)

    def test_nothing_to_unlock_returns_400_without_charging(self):
        JobMatch.objects.filter(resume=self.resume).update(is_unlocked=True)

        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._solde(), 3, "aucun crédit ne doit être débité")

    def test_another_users_resume_is_refused(self):
        """Sans ce contrôle, on débloque — et facture — sur le CV d'autrui."""
        intrus = User.objects.create_user(email="intrus@example.com", password="MotDePasse!2024")
        self.client.force_login(intrus)

        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(JobMatch.objects.filter(is_unlocked=True).count(), 0)

    def test_premium_user_is_not_charged(self):
        self.user.subscription_end_date = timezone.now() + timedelta(days=10)
        self.user.save(update_fields=["subscription_end_date"])

        self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(self._solde(), 3)
        self.assertEqual(JobMatch.objects.filter(is_unlocked=True).count(), 3)

    def test_get_is_rejected(self):
        """Un déblocage facturé ne doit pas s'exécuter sur une simple visite d'URL."""
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_failure_after_debit_refunds_the_credit(self):
        """
        Si la mise à jour échoue après le débit, le crédit doit être rendu :
        l'utilisateur aurait payé pour un déblocage qui n'a pas eu lieu.
        """
        # Le patch doit viser le seul queryset de la vue. Remplacer
        # QuerySet.update globalement casserait aussi le débit du crédit, qui
        # s'appuie dessus — le test ne vérifierait alors plus rien.
        faux = MagicMock()
        queryset = faux.objects.filter.return_value
        queryset.count.return_value = 3
        queryset.update.side_effect = RuntimeError("base indisponible")

        with patch("matching.views.JobMatch", faux):
            response = self.client.post(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._solde(), 3, "le crédit doit avoir été remboursé")
        # Le remboursement doit laisser une trace, pas seulement rétablir le solde.
        self.assertTrue(
            CreditEntry.objects.filter(reason=CreditEntry.Reason.REFUND).exists(),
            "le remboursement doit être écrit au registre",
        )


class UpdateMatchStatusTests(MatchingFixtureMixin, TestCase):
    def setUp(self):
        self.user, self.resume, self.matches = self.build(verrouillees=1)
        self.match = self.matches[0]
        self.client.force_login(self.user)
        self.url = reverse("update_match_status", kwargs={"match_id": self.match.pk})

    def test_valid_status_is_saved(self):
        self.client.post(self.url, {"status": "applied"}, HTTP_REFERER="/dashboard/")
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "applied")

    def test_invalid_status_is_ignored(self):
        self.client.post(self.url, {"status": "n_importe_quoi"}, HTTP_REFERER="/dashboard/")
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "new")

    def test_another_user_cannot_change_the_status(self):
        intrus = User.objects.create_user(email="intrus@example.com", password="MotDePasse!2024")
        self.client.force_login(intrus)

        response = self.client.post(self.url, {"status": "applied"}, HTTP_REFERER="/")

        self.assertEqual(response.status_code, 404)
        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "new")


class ExportPdfTests(MatchingFixtureMixin, TestCase):
    """
    L'export PDF n'appelle aucun modèle : il ne doit rien facturer.

    Il passe par `quick_refine_cover_letter` avec action=export-pdf, et non par
    la vue `export_cover_letter_pdf` — celle-ci n'a jamais eu d'URL.
    """

    def setUp(self):
        self.user, self.resume, matches = self.build(verrouillees=1)
        self.match = matches[0]
        self.match.cover_letter_content = "Madame, Monsieur, je vous écris…"
        self.match.save(update_fields=["cover_letter_content"])
        self.client.force_login(self.user)
        self.url = reverse("quick_refine_cover_letter", kwargs={"match_id": self.match.pk})

    @patch("matching.views.AILetterGenerator")
    def test_export_does_not_consume_a_credit(self, generateur):
        generateur.return_value.export_to_pdf.return_value = __import__("io").BytesIO(b"%PDF-1.4")

        response = self.client.post(
            self.url,
            {"action": "export-pdf", "cover_letter_content": "Bonjour"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 3)
        self.assertEqual(
            CreditEntry.objects.filter(reason=CreditEntry.Reason.CONSUMPTION).count(), 0
        )

    def test_empty_letter_is_refused_before_any_work(self):
        response = self.client.post(
            self.url,
            {"action": "export-pdf", "cover_letter_content": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)

    def test_another_user_cannot_export(self):
        intrus = User.objects.create_user(email="intrus@example.com", password="MotDePasse!2024")
        self.client.force_login(intrus)
        response = self.client.post(
            self.url, {"action": "export-pdf"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 404)
