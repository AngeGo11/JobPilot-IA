"""
Peuple une base de développement avec un jeu de données réaliste.

Objectif : pouvoir travailler sur le back-office et le matching sans jamais
brancher un poste de développement sur la base de production. La commande est
idempotente et refuse de s'exécuter sur une base qui n'est pas locale.

    python manage.py seed_demo
    python manage.py seed_demo --users 200 --reset
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from administration.models import TaskRun
from matching.models import JobAlert, JobMatch, JobOffer
from resumes.models import Resume
from subscriptions.models import Transaction
from users.models import CandidateProfile, SubscriptionPlan

User = get_user_model()

# Hôtes considérés comme locaux. Toute autre valeur fait échouer la commande :
# un seed exécuté par erreur sur la production créerait de faux utilisateurs
# au milieu des vrais, sans moyen simple de les distinguer ensuite.
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1", "db", "postgres"}

DEMO_DOMAIN = "demo.jobpilot.local"

FIRST_NAMES = [
    "Camille", "Yanis", "Fatou", "Lucas", "Inès", "Mehdi", "Chloé", "Antoine",
    "Sarah", "Thomas", "Awa", "Julien", "Manon", "Rayan", "Léa", "Hugo",
    "Nour", "Maxime", "Clara", "Samuel",
]
LAST_NAMES = [
    "Bernard", "Diallo", "Martin", "Nguyen", "Petit", "Moreau", "Lefebvre",
    "Garcia", "Roux", "Traoré", "Fontaine", "Chevalier", "Marchand", "Barbier",
]
JOB_TITLES = [
    "Développeur Python", "Data Engineer", "Ingénieur DevOps", "Développeur Full Stack",
    "Analyste Data", "Administrateur Systèmes", "Développeur Backend Java",
    "Chef de projet technique", "Ingénieur QA", "Développeur Frontend React",
]
COMPANIES = [
    "Atos", "Capgemini", "Sopra Steria", "Thales", "OVHcloud", "Doctolib",
    "BlaBlaCar", "Dataiku", "Alan", "Qonto", "Back Market", "Swile",
]
CITIES = [
    "Paris (75)", "Lyon (69)", "Toulouse (31)", "Nantes (44)", "Bordeaux (33)",
    "Lille (59)", "Rennes (35)", "Marseille (13)", "Strasbourg (67)",
]
CONTRACTS = ["CDI", "CDD", "Alternance", "Stage"]
SKILLS = [
    "Python", "Django", "PostgreSQL", "Docker", "Git", "React", "TypeScript",
    "Kubernetes", "Terraform", "Pandas", "Spark", "Java", "Spring", "CI/CD",
]


class Command(BaseCommand):
    help = "Peuple une base de développement avec des données de démonstration."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=120, help="Nombre de comptes à créer (défaut : 120).")
        parser.add_argument("--offers", type=int, default=60, help="Nombre d'offres à créer (défaut : 60).")
        parser.add_argument("--reset", action="store_true", help="Supprime les données de démo existantes avant de recréer.")
        parser.add_argument("--seed", type=int, default=42, help="Graine aléatoire, pour un jeu de données reproductible.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignore le garde-fou « base locale ». À n'utiliser qu'en connaissance de cause.",
        )

    def handle(self, *args, **options):
        self._guard_local_database(force=options["force"])

        rng = random.Random(options["seed"])

        if options["reset"]:
            deleted = self._reset()
            self.stdout.write(self.style.WARNING(f"Réinitialisation : {deleted} compte(s) de démo supprimé(s)."))

        with transaction.atomic():
            admin = self._create_admin()
            users = self._create_users(rng, options["users"])
            offers = self._create_offers(rng, options["offers"])
            self._create_activity(rng, users, offers)
            self._create_task_runs()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Jeu de données de démonstration prêt."))
        self.stdout.write(f"  Comptes      : {User.objects.count()}")
        self.stdout.write(f"  CV           : {Resume.objects.count()}")
        self.stdout.write(f"  Offres       : {JobOffer.objects.count()}")
        self.stdout.write(f"  Matchs       : {JobMatch.objects.count()}")
        self.stdout.write(f"  Transactions : {Transaction.objects.count()}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  Back-office : {admin.email} / demo"))

    # --- Garde-fous ---------------------------------------------------------

    def _guard_local_database(self, force):
        from django.db import connection

        host = (connection.settings_dict.get("HOST") or "").lower()
        if host in LOCAL_HOSTS or force:
            if force and host not in LOCAL_HOSTS:
                self.stdout.write(self.style.ERROR(f"--force : exécution sur l'hôte distant « {host} »."))
            return
        raise CommandError(
            f"Base non locale détectée (HOST = « {host} »). "
            "Cette commande crée des comptes fictifs et ne doit jamais toucher la production. "
            "Pointez DATABASE_URL sur votre base locale, ou passez --force si c'est réellement voulu."
        )

    def _reset(self):
        """Supprime uniquement les comptes de démo, reconnaissables à leur domaine."""
        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        count = demo_users.count()
        demo_users.delete()  # cascade sur CV, matchs, transactions
        JobOffer.objects.filter(remote_id__startswith="DEMO-").delete()
        TaskRun.objects.filter(name__in=["check_new_offers", "cleanup_expired_alerts"]).delete()
        return count

    # --- Création -----------------------------------------------------------

    def _create_admin(self):
        admin, created = User.objects.get_or_create(
            email=f"admin@{DEMO_DOMAIN}",
            defaults={"first_name": "Admin", "last_name": "Démo", "is_staff": True, "is_superuser": True},
        )
        if created or not admin.check_password("demo"):
            admin.set_password("demo")
            admin.is_staff = True
            admin.is_superuser = True
            admin.save()
        return admin

    def _create_users(self, rng, count):
        now = timezone.now()
        users = []
        for index in range(count):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            email = f"{first.lower()}.{last.lower()}{index}@{DEMO_DOMAIN}"
            if User.objects.filter(email=email).exists():
                continue

            # Inscriptions étalées sur 90 jours, avec une densité croissante :
            # une courbe plate ne montrerait pas si le graphique fonctionne.
            days_ago = int(90 * (rng.random() ** 1.7))
            joined = now - timedelta(days=days_ago, hours=rng.randint(0, 23))

            user = User(
                email=email,
                username=email,
                first_name=first,
                last_name=last,
                date_joined=joined,
                is_active=rng.random() > 0.04,
                ai_credits=rng.choice([0, 0, 2, 5, 5, 8, 12]),
            )
            user.set_password("demo")

            # ~18 % d'abonnés, dont quelques-uns expirés et quelques échéances proches.
            roll = rng.random()
            if roll < 0.18:
                plan = rng.choice([SubscriptionPlan.PASS24H, SubscriptionPlan.SPRINT, SubscriptionPlan.PRO])
                user.subscription_plan = plan
                if rng.random() < 0.25:
                    user.subscription_end_date = now - timedelta(days=rng.randint(1, 40))
                else:
                    user.subscription_end_date = now + timedelta(days=rng.randint(1, 45))
            if rng.random() > 0.25:
                user.last_login = joined + timedelta(days=rng.randint(0, max(days_ago, 1)))
            users.append(user)

        User.objects.bulk_create(users, batch_size=200)
        created = list(User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}").exclude(is_superuser=True))
        CandidateProfile.objects.bulk_create(
            [
                CandidateProfile(user=u, location=rng.choice(CITIES), is_available=rng.random() > 0.2)
                for u in created
                if not CandidateProfile.objects.filter(user=u).exists()
            ],
            batch_size=200,
            ignore_conflicts=True,
        )
        return created

    def _create_offers(self, rng, count):
        now = timezone.now()
        existing = set(JobOffer.objects.values_list("remote_id", flat=True))
        offers = [
            JobOffer(
                remote_id=f"DEMO-{index:05d}",
                title=rng.choice(JOB_TITLES),
                company_name=rng.choice(COMPANIES),
                description=" ".join(rng.sample(SKILLS, k=6)) + " équipe agile projet technique",
                url=f"https://candidat.francetravail.fr/offres/DEMO-{index:05d}",
                location=rng.choice(CITIES),
                contract_type=rng.choice(CONTRACTS),
                date_posted=now - timedelta(days=rng.randint(0, 45)),
                raw_api_data={},
            )
            for index in range(count)
            if f"DEMO-{index:05d}" not in existing
        ]
        JobOffer.objects.bulk_create(offers, batch_size=200)
        return list(JobOffer.objects.filter(remote_id__startswith="DEMO-"))

    def _create_activity(self, rng, users, offers):
        """CV, alertes et matchs — avec un entonnoir d'activation réaliste."""
        now = timezone.now()
        resumes, alerts, matches = [], [], []

        for user in users:
            if rng.random() > 0.62:  # ~62 % déposent un CV
                continue
            title = rng.choice(JOB_TITLES)
            resume = Resume(
                user=user,
                title=f"CV {title}",
                file=f"cvs/demo_{user.pk}.pdf",
                is_primary=True,
                uploaded_at=user.date_joined + timedelta(hours=rng.randint(1, 72)),
                detected_job_title=title if rng.random() > 0.12 else None,
                detected_skills=rng.sample(SKILLS, k=rng.randint(3, 7)),
                extracted_text=f"{title} " + " ".join(rng.sample(SKILLS, k=8)),
            )
            resumes.append(resume)

        Resume.objects.bulk_create(resumes, batch_size=200)
        saved_resumes = list(Resume.objects.filter(user__email__endswith=f"@{DEMO_DOMAIN}"))

        for resume in saved_resumes:
            if rng.random() < 0.35:
                alerts.append(
                    JobAlert(
                        resume=resume,
                        is_active=rng.random() > 0.25,
                        last_checked=now - timedelta(hours=rng.randint(1, 96)) if rng.random() > 0.2 else None,
                    )
                )
            for offer in rng.sample(offers, k=min(rng.randint(2, 8), len(offers))):
                unlocked = rng.random() < 0.45
                matches.append(
                    JobMatch(
                        resume=resume,
                        user=resume.user,
                        job_offer=offer,
                        score=rng.randint(45, 98),
                        is_unlocked=unlocked,
                        status=rng.choice(["new", "new", "seen", "applied", "rejected"]) if unlocked else "new",
                        matched_at=resume.uploaded_at + timedelta(hours=rng.randint(1, 240)),
                    )
                )

        JobAlert.objects.bulk_create(alerts, batch_size=200, ignore_conflicts=True)
        JobMatch.objects.bulk_create(matches, batch_size=500, ignore_conflicts=True)

        # Transactions : uniquement pour les comptes ayant un plan.
        prices = {
            SubscriptionPlan.PASS24H: Decimal("2.99"),
            SubscriptionPlan.SPRINT: Decimal("5.99"),
            SubscriptionPlan.PRO: Decimal("14.99"),
        }
        transactions = []
        for user in users:
            if not user.subscription_plan:
                continue
            for occurrence in range(rng.randint(1, 4)):
                transactions.append(
                    Transaction(
                        user=user,
                        stripe_session_id=f"cs_demo_{user.pk}_{occurrence}",
                        amount=prices.get(user.subscription_plan, Decimal("4.99")),
                        created_at=now - timedelta(days=rng.randint(0, 120)),
                    )
                )
        Transaction.objects.bulk_create(transactions, batch_size=500, ignore_conflicts=True)
        # `created_at` est auto_now_add : bulk_create l'ignore, on réécrit les dates
        # pour que le graphique des revenus par mois ne soit pas un pic unique.
        for tx in transactions:
            Transaction.objects.filter(stripe_session_id=tx.stripe_session_id).update(created_at=tx.created_at)

    def _create_task_runs(self):
        now = timezone.now()
        runs = []
        for hours_ago in (2, 8, 14, 20, 26):
            runs.append(
                TaskRun(
                    name="check_new_offers",
                    status=TaskRun.Status.SUCCESS if hours_ago != 14 else TaskRun.Status.ERROR,
                    started_at=now - timedelta(hours=hours_ago),
                    finished_at=now - timedelta(hours=hours_ago) + timedelta(seconds=42),
                    items_processed=0 if hours_ago == 14 else 12,
                    message="" if hours_ago != 14 else "ConnectionError: API France Travail injoignable",
                )
            )
        runs.append(
            TaskRun(
                name="cleanup_expired_alerts",
                status=TaskRun.Status.SUCCESS,
                started_at=now - timedelta(hours=6),
                finished_at=now - timedelta(hours=6) + timedelta(seconds=3),
                items_processed=4,
            )
        )
        TaskRun.objects.bulk_create(runs)
