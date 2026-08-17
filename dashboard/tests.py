"""
Tests du tableau de bord candidat.

L'app n'en avait aucun. Ce sont pourtant les deux vues que chaque utilisateur
voit à chaque visite, et celles qui décident quelles candidatures lui sont
montrées — donc celles où une erreur de filtre exposerait les données d'un
candidat à un autre.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from matching.models import JobMatch, JobOffer
from resumes.models import Resume

User = get_user_model()


class DashboardFixtureMixin:
    def build_candidat(self, email="c@example.com"):
        user = User.objects.create_user(email=email, password="MotDePasse!2024")
        resume = Resume.objects.create(user=user, title="CV", file="cvs/a.pdf")
        return user, resume

    def add_match(self, user, resume, *, remote_id, unlocked=True, status="new", score=80):
        offre = JobOffer.objects.create(remote_id=remote_id, title=f"Poste {remote_id}")
        return JobMatch.objects.create(
            resume=resume, user=user, job_offer=offre,
            score=score, is_unlocked=unlocked, status=status,
        )


class DashboardViewTests(DashboardFixtureMixin, TestCase):
    def setUp(self):
        self.user, self.resume = self.build_candidat()
        self.client.force_login(self.user)
        self.url = reverse("dashboard")

    def test_anonymous_is_redirected(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_locked_offers_are_hidden(self):
        """
        Une offre non débloquée n'a pas été payée : la montrer donnerait
        gratuitement ce que le crédit est censé acheter.
        """
        self.add_match(self.user, self.resume, remote_id="A", unlocked=True)
        self.add_match(self.user, self.resume, remote_id="B", unlocked=False)

        response = self.client.get(self.url)

        self.assertEqual(response.context["stats"]["total"], 1)
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_rejected_offers_are_hidden(self):
        self.add_match(self.user, self.resume, remote_id="A", status="new")
        self.add_match(self.user, self.resume, remote_id="B", status="rejected")

        self.assertEqual(self.client.get(self.url).context["stats"]["total"], 1)

    def test_another_candidates_matches_are_never_shown(self):
        autre, son_cv = self.build_candidat(email="autre@example.com")
        self.add_match(autre, son_cv, remote_id="AUTRE")
        self.add_match(self.user, self.resume, remote_id="MIEN")

        response = self.client.get(self.url)

        self.assertEqual(response.context["stats"]["total"], 1)
        titres = [m.job_offer.remote_id for m in response.context["page_obj"]]
        self.assertEqual(titres, ["MIEN"])

    def test_statistics_count_each_status(self):
        self.add_match(self.user, self.resume, remote_id="A", status="new")
        self.add_match(self.user, self.resume, remote_id="B", status="seen")
        self.add_match(self.user, self.resume, remote_id="C", status="applied")

        stats = self.client.get(self.url).context["stats"]

        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["new"], 1)
        self.assertEqual(stats["seen"], 1)
        self.assertEqual(stats["applied"], 1)

    def test_resume_count_is_specific_to_the_user(self):
        autre, _ = self.build_candidat(email="autre@example.com")
        Resume.objects.create(user=autre, title="CV tiers", file="cvs/b.pdf")

        self.assertEqual(self.client.get(self.url).context["resume_count"], 1)

    def test_welcome_modal_is_shown_once(self):
        session = self.client.session
        session["show_welcome_modal"] = True
        session.save()

        self.assertTrue(self.client.get(self.url).context["show_welcome"])
        # Deuxième visite : la modale ne doit plus revenir.
        self.assertFalse(self.client.get(self.url).context["show_welcome"])

    def test_pagination_caps_the_page(self):
        for index in range(12):
            self.add_match(self.user, self.resume, remote_id=f"P{index}")

        page = self.client.get(self.url).context["page_obj"]

        self.assertEqual(len(page), 10)
        self.assertEqual(page.paginator.count, 12)


class ApplicationWorkspaceTests(DashboardFixtureMixin, TestCase):
    def setUp(self):
        self.user, self.resume = self.build_candidat()
        self.match = self.add_match(self.user, self.resume, remote_id="A", unlocked=True)
        self.client.force_login(self.user)
        self.url = reverse("application_workspace", kwargs={"match_id": self.match.pk})

    def test_owner_can_open_the_workspace(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["match"], self.match)

    def test_locked_offer_is_not_accessible(self):
        """Le workspace donne accès au détail de l'offre : il exige le déblocage."""
        self.match.is_unlocked = False
        self.match.save(update_fields=["is_unlocked"])

        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_another_candidate_gets_404(self):
        intrus = User.objects.create_user(email="intrus@example.com", password="MotDePasse!2024")
        self.client.force_login(intrus)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_saving_the_letter_persists_it(self):
        self.client.post(self.url, {"save": "1", "cover_letter_content": "Madame, Monsieur…"})

        self.match.refresh_from_db()
        self.assertEqual(self.match.cover_letter_content, "Madame, Monsieur…")
        self.assertEqual(self.match.status, "new", "sauvegarder ne vaut pas postuler")

    def test_marking_as_applied_changes_the_status(self):
        self.client.post(
            self.url, {"mark_as_applied": "1", "cover_letter_content": "Ma lettre"}
        )

        self.match.refresh_from_db()
        self.assertEqual(self.match.status, "applied")
        self.assertEqual(self.match.cover_letter_content, "Ma lettre")

    def test_another_candidate_cannot_write_the_letter(self):
        intrus = User.objects.create_user(email="intrus@example.com", password="MotDePasse!2024")
        self.client.force_login(intrus)

        self.client.post(self.url, {"save": "1", "cover_letter_content": "injecté"})

        self.match.refresh_from_db()
        self.assertEqual(self.match.cover_letter_content, "")
