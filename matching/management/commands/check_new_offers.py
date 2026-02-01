"""
Commande Django : python manage.py check_new_offers
Pour chaque JobAlert active, interroge l'API France Travail pour les offres publiées après last_checked,
calcule le score de matching, et envoie un email récapitulatif si des offres pertinentes (score >= 70%) sont trouvées.
"""
import logging
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import reverse

from matching.models import JobAlert
from matching.services.francetravail import FranceTravail


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Vérifie les nouvelles offres pour chaque alerte active et envoie un email récapitulatif si pertinent."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Ne pas sauvegarder les matches ni envoyer d\'emails.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=30,
            help='Nombre max d\'offres à récupérer par alerte (défaut: 30).',
        )
        parser.add_argument(
            '--min-score',
            type=int,
            default=70,
            help='Score minimum pour considérer une offre comme pertinente (défaut: 70).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options['limit']
        min_score = options['min_score']

        if dry_run:
            self.stdout.write(self.style.WARNING("Mode dry-run : aucun enregistrement ni email."))

        alerts = JobAlert.objects.filter(is_active=True).select_related('resume', 'resume__user')
        if not alerts.exists():
            self.stdout.write("Aucune alerte active.")
            return

        ft = None
        try:
            ft = FranceTravail()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erreur initialisation France Travail : {e}"))
            logger.exception("check_new_offers: FranceTravail init failed")
            return

        for alert in alerts:
            try:
                self._process_alert(alert, ft, dry_run, limit, min_score)
            except Exception as e:
                logger.exception("check_new_offers: erreur pour alerte %s", alert.pk)
                self.stderr.write(self.style.ERROR(f"Alerte {alert.pk} : {e}"))

    def _process_alert(self, alert, ft, dry_run, limit, min_score):
        resume = alert.resume
        user = resume.user
        keywords = (resume.detected_job_title or "").strip()
        if not keywords:
            self.stdout.write(f"  Alerte {alert.pk} : pas de titre de poste détecté pour le CV « {resume.title} », ignorée.")
            return

        last_checked = alert.last_checked
        # Offres publiées après last_checked (si None, on prend toutes celles retournées par l'API pour cette exécution)
        try:
            results = ft.search_jobs(keywords, page=1, limit=limit)
        except Exception as e:
            logger.warning("check_new_offers: API search_jobs failed for alert %s: %s", alert.pk, e)
            self.stderr.write(self.style.WARNING(f"  API France Travail échouée pour alerte {alert.pk} : {e}"))
            return

        if not results:
            if not dry_run:
                alert.last_checked = timezone.now()
                alert.save(update_fields=['last_checked'])
            return

        # Filtrer par date : garder uniquement les offres publiées après last_checked
        if last_checked:
            last_checked_aware = timezone.make_aware(last_checked) if timezone.is_naive(last_checked) else last_checked
            filtered = []
            for r in results:
                created = parse_datetime(r.get('dateCreation'))
                if not created:
                    continue
                if timezone.is_naive(created):
                    created = timezone.make_aware(created)
                if created > last_checked_aware:
                    filtered.append(r)
            results = filtered
        # Si last_checked est None (première exécution), on ne déclenche pas d'email pour éviter le spam
        first_run = last_checked is None

        # Filtrer par score (matching simplifié par mots-clés)
        resume_text = (resume.extracted_text or "").strip()
        new_offers_data = []
        for r in results:
            desc = (r.get('description') or "")
            score = ft.calculate_match_score(resume_text, desc)
            if score >= min_score:
                new_offers_data.append(r)

        if not new_offers_data:
            if not dry_run:
                alert.last_checked = timezone.now()
                alert.save(update_fields=['last_checked'])
            return

        if not dry_run:
            try:
                saved_matches = ft.save_jobs(new_offers_data, user, resume)
            except Exception as e:
                logger.exception("check_new_offers: save_jobs failed for alert %s", alert.pk)
                self.stderr.write(self.style.ERROR(f"  Erreur sauvegarde des offres pour alerte {alert.pk} : {e}"))
                return

            alert.last_checked = timezone.now()
            alert.save(update_fields=['last_checked'])

            # Envoyer l'email récapitulatif uniquement si ce n'est pas la première exécution (éviter spam)
            if not first_run and user.email:
                site_url = getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
                dashboard_path = reverse('dashboard')
                dashboard_url = site_url + dashboard_path
                subject = f"JobPilot : {len(saved_matches)} nouvelle(s) offre(s) pour vous"
                message = (
                    f"Bonjour,\n\n"
                    f"Votre alerte basée sur le CV « {resume.title} » a détecté {len(saved_matches)} "
                    f"nouvelle(s) offre(s) correspondant à votre profil (score >= {min_score}%).\n\n"
                    f"Consultez votre tableau de bord pour voir les offres et postuler :\n{dashboard_url}\n\n"
                    f"Cordialement,\nL'équipe JobPilot"
                )
                try:
                    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jobpilot.local')
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=from_email,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                    self.stdout.write(self.style.SUCCESS(f"  Alerte {alert.pk} : {len(saved_matches)} offre(s), email envoyé à {user.email}"))
                except Exception as e:
                    logger.exception("check_new_offers: send_mail failed for alert %s", alert.pk)
                    self.stderr.write(self.style.ERROR(f"  Envoi email échoué pour alerte {alert.pk} : {e}"))
            elif first_run:
                self.stdout.write(f"  Alerte {alert.pk} : {len(saved_matches)} offre(s) (première exécution, pas d'email).")
        else:
            self.stdout.write(f"  [dry-run] Alerte {alert.pk} : {len(new_offers_data)} offre(s) pertinente(s) auraient été enregistrées.")
