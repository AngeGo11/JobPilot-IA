"""Tests du back-office : accès, rendu des pages et actions."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from administration.models import AdminAuditLog, SiteSettings, TaskRun
from matching.models import JobAlert, JobMatch, JobOffer
from resumes.models import Resume
from subscriptions.models import Transaction

User = get_user_model()

PAGES = ["overview", "users", "revenue", "content", "supervision", "audit"]


class AdminAccessTests(TestCase):
    """Le back-office ne doit être atteignable que par l'équipe."""

    @classmethod
    def setUpTestData(cls):
        cls.candidate = User.objects.create_user(email="candidat@example.com", password="MotDePasse!2024")
        cls.staff = User.objects.create_user(
            email="staff@example.com", password="MotDePasse!2024", is_staff=True
        )

    def setUp(self):
        cache.clear()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("administration:overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_candidate_gets_403(self):
        self.client.force_login(self.candidate)
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f"administration:{name}")).status_code, 403)

    def test_settings_page_requires_superuser(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("administration:settings")).status_code, 403)

    def test_staff_can_open_every_page(self):
        self.client.force_login(self.staff)
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f"administration:{name}")).status_code, 200)


class AdminPagesWithDataTests(TestCase):
    """Les pages doivent rendre correctement avec des données réelles."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(email="admin@example.com", password="MotDePasse!2024")
        cls.user = User.objects.create_user(
            email="client@example.com",
            password="MotDePasse!2024",
            subscription_plan="pro",
            subscription_end_date=timezone.now() + timedelta(days=5),
        )
        resume = Resume.objects.create(
            user=cls.user, title="CV Data", file="cvs/test.pdf", detected_job_title="Data Engineer"
        )
        JobAlert.objects.create(resume=resume, is_active=True)
        offer = JobOffer.objects.create(remote_id="FT-1", title="Data Engineer", company_name="ACME")
        JobMatch.objects.create(
            resume=resume, user=cls.user, job_offer=offer, score=88, is_unlocked=True, status="applied"
        )
        Transaction.objects.create(
            user=cls.user, stripe_session_id="cs_test_1", amount=Decimal("14.99")
        )
        # Transaction sans montant : ne doit pas casser les agrégations.
        Transaction.objects.create(user=cls.user, stripe_session_id="cs_test_2")
        TaskRun.objects.create(
            name="check_new_offers",
            status=TaskRun.Status.SUCCESS,
            finished_at=timezone.now(),
            items_processed=3,
        )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)

    def test_all_pages_render(self):
        for name in PAGES + ["settings"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f"administration:{name}")).status_code, 200)

    def test_overview_shows_counts(self):
        response = self.client.get(reverse("administration:overview"))
        self.assertEqual(response.context["users"]["total"], 2)
        self.assertEqual(response.context["users"]["premium"], 1)
        self.assertEqual(response.context["revenue"]["total"], Decimal("14.99"))
        self.assertEqual(response.context["revenue"]["untracked_count"], 1)

    def test_user_detail_is_logged(self):
        response = self.client.get(reverse("administration:user_detail", args=[self.user.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminAuditLog.objects.filter(
                action=AdminAuditLog.Action.USER_VIEWED, target=f"utilisateur #{self.user.pk}"
            ).exists()
        )

    def test_user_search_and_filters(self):
        url = reverse("administration:users")
        self.assertEqual(len(self.client.get(url, {"q": "client"}).context["page_obj"]), 1)
        self.assertEqual(len(self.client.get(url, {"status": "premium"}).context["page_obj"]), 1)
        self.assertEqual(len(self.client.get(url, {"plan": "pro"}).context["page_obj"]), 1)

    def test_csv_export_excludes_personal_data(self):
        response = self.client.get(reverse("administration:export_users"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertNotIn(self.user.email, body)
        self.assertIn("nb_matchs", body)

    def test_health_json(self):
        response = self.client.get(reverse("administration:health_json"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["overall"], {"ok", "warn", "error"})
        self.assertTrue(payload["checks"])


class UserActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(email="admin@example.com", password="MotDePasse!2024")
        cls.user = User.objects.create_user(email="client@example.com", password="MotDePasse!2024")

    def setUp(self):
        cache.clear()
        self.client.force_login(self.admin)
        self.url = reverse("administration:user_action", args=[self.user.pk])

    def test_grant_credits(self):
        self.client.post(self.url, {"action": "grant_credits", "amount": 10, "reason": "geste"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 15)

    def test_credits_never_go_negative(self):
        self.client.post(self.url, {"action": "grant_credits", "amount": -100, "reason": "correction"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 0)

    def test_toggle_active(self):
        self.client.post(self.url, {"action": "toggle_active"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_admin_cannot_deactivate_self(self):
        url = reverse("administration:user_action", args=[self.admin.pk])
        self.client.post(url, {"action": "toggle_active"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_extend_expired_subscription_starts_from_now(self):
        self.user.subscription_end_date = timezone.now() - timedelta(days=30)
        self.user.save(update_fields=["subscription_end_date"])
        self.client.post(self.url, {"action": "extend_subscription", "days": 7, "reason": "incident"})
        self.user.refresh_from_db()
        self.assertGreater(self.user.subscription_end_date, timezone.now() + timedelta(days=6))
        self.assertLess(self.user.subscription_end_date, timezone.now() + timedelta(days=8))

    def test_actions_are_audited(self):
        self.client.post(self.url, {"action": "grant_credits", "amount": 3, "reason": "test"})
        entry = AdminAuditLog.objects.filter(action=AdminAuditLog.Action.CREDITS_GRANTED).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.details["reason"], "test")
        self.assertEqual(entry.actor, self.admin)


class SiteSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser(email="admin@example.com", password="MotDePasse!2024")

    def test_singleton(self):
        first = SiteSettings.load()
        cache.clear()
        second = SiteSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_save_updates_and_audits(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("administration:settings"), {
            "maintenance_mode": "",
            "maintenance_message": "Retour bientôt.",
            "registrations_open": "on",
            "signup_free_credits": 8,
            "max_resumes_per_user": 5,
            "matching_min_score": 75,
            "alerts_enabled": "on",
            "alerts_max_offers_per_email": 10,
            "contact_email": "contact@jobpilot.ai",
            "support_notice": "",
        })
        self.assertEqual(response.status_code, 302)
        settings_obj = SiteSettings.load()
        self.assertEqual(settings_obj.matching_min_score, 75)
        self.assertEqual(settings_obj.updated_by, self.admin)
        self.assertTrue(
            AdminAuditLog.objects.filter(action=AdminAuditLog.Action.SETTINGS_UPDATED).exists()
        )

    def test_maintenance_requires_message(self):
        from administration.forms import SiteSettingsForm

        form = SiteSettingsForm(data={
            "maintenance_mode": "on",
            "maintenance_message": "   ",
            "registrations_open": "on",
            "signup_free_credits": 5,
            "max_resumes_per_user": 5,
            "matching_min_score": 70,
            "alerts_enabled": "on",
            "alerts_max_offers_per_email": 10,
            "contact_email": "",
            "support_notice": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("maintenance_message", form.errors)


class MaintenanceModeTests(TestCase):
    def setUp(self):
        cache.clear()
        settings_obj = SiteSettings.load()
        settings_obj.maintenance_mode = True
        settings_obj.maintenance_message = "Retour dans une heure."
        settings_obj.save()

    def tearDown(self):
        cache.clear()

    def test_visitor_gets_503(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "Retour dans une heure.", status_code=503)

    def test_staff_passes_through(self):
        staff = User.objects.create_user(
            email="staff@example.com", password="MotDePasse!2024", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_backoffice_stays_reachable(self):
        """Sinon activer la maintenance couperait le moyen de la désactiver."""
        admin = User.objects.create_superuser(email="admin@example.com", password="MotDePasse!2024")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("administration:settings")).status_code, 200)


class RegistrationSwitchTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_registration_closed_blocks_post(self):
        settings_obj = SiteSettings.load()
        settings_obj.registrations_open = False
        settings_obj.save()

        response = self.client.post(reverse("register"), {
            "first_name": "Jean", "last_name": "Dupont",
            "email": "nouveau@example.com",
            "password1": "MotDePasseTresLong!2024", "password2": "MotDePasseTresLong!2024",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(email="nouveau@example.com").exists())

    def test_signup_credits_follow_settings(self):
        settings_obj = SiteSettings.load()
        settings_obj.signup_free_credits = 12
        settings_obj.save()

        self.client.post(reverse("register"), {
            "first_name": "Jean", "last_name": "Dupont",
            "email": "nouveau@example.com",
            "password1": "MotDePasseTresLong!2024", "password2": "MotDePasseTresLong!2024",
        })
        user = User.objects.filter(email="nouveau@example.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.ai_credits, 12)


class TaskTrackingTests(TestCase):
    def test_success_is_recorded(self):
        from administration.services.tasks import track_run

        with track_run("demo") as run:
            run.items_processed = 4
        entry = TaskRun.objects.get(name="demo")
        self.assertEqual(entry.status, TaskRun.Status.SUCCESS)
        self.assertEqual(entry.items_processed, 4)
        self.assertIsNotNone(entry.finished_at)

    def test_error_is_recorded_and_reraised(self):
        from administration.services.tasks import track_run

        with self.assertRaises(ValueError):
            with track_run("demo_ko"):
                raise ValueError("boum")
        entry = TaskRun.objects.get(name="demo_ko")
        self.assertEqual(entry.status, TaskRun.Status.ERROR)
        self.assertIn("boum", entry.message)


class QuotaAndNoticeTests(TestCase):
    """Les réglages du back-office doivent produire un effet réel sur le site."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="client@example.com", password="MotDePasse!2024")
        self.client.force_login(self.user)

    def tearDown(self):
        cache.clear()

    def test_resume_quota_blocks_upload_page(self):
        settings_obj = SiteSettings.load()
        settings_obj.max_resumes_per_user = 1
        settings_obj.save()
        Resume.objects.create(user=self.user, title="CV 1", file="cvs/a.pdf")

        response = self.client.get(reverse("upload_resume"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("resume_list"), response["Location"])

    def test_support_notice_is_displayed(self):
        settings_obj = SiteSettings.load()
        settings_obj.support_notice = "Maintenance prévue dimanche."
        settings_obj.save()
        self.assertContains(self.client.get(reverse("dashboard")), "Maintenance prévue dimanche.")
