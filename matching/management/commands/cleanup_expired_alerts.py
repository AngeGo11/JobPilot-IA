from django.core.management.base import BaseCommand
from django.utils import timezone

from administration.services.tasks import track_run
from matching.models import JobAlert


class Command(BaseCommand):
    help = "Désactive les alertes des utilisateurs dont l'abonnement a expiré."

    def handle(self, *args, **options):
        # Trace d'exécution pour la page de supervision du back-office.
        with track_run("cleanup_expired_alerts") as run:
            now = timezone.now()

            # Sélectionne les alertes actives liées à des utilisateurs dont l'abonnement est expiré
            # (subscription_end_date <= maintenant OU subscription_end_date est null)
            # Note : Si un utilisateur n'a jamais eu d'abonnement (null), ses alertes devraient être inactives,
            # mais cette commande assure le nettoyage global.

            expired_alerts = JobAlert.objects.filter(
                is_active=True
            ).filter(
                resume__user__subscription_end_date__lte=now
            )

            count = expired_alerts.count()
            if count > 0:
                expired_alerts.update(is_active=False)
                self.stdout.write(self.style.SUCCESS(f"{count} alerte(s) désactivée(s) car l'abonnement a expiré."))
            else:
                self.stdout.write("Aucune alerte expirée à nettoyer.")

            run.items_processed = count
