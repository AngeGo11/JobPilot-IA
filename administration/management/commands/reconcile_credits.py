"""
Compare le solde de crédits de chaque compte à la somme de son registre.

Deux usages :

    python manage.py reconcile_credits            # diagnostic seul
    python manage.py reconcile_credits --fix      # écrit les régularisations

Les comptes créés avant l'introduction de `CreditEntry` ont un solde sans
aucune écriture correspondante. `--fix` leur pose une écriture d'ouverture,
après quoi l'invariant « solde = somme du registre » devient vérifiable pour
tout le monde : toute dérive ultérieure signale une mutation passée à côté du
service `subscriptions.services.credits`.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Sum

from subscriptions.models import CreditEntry

User = get_user_model()


class Command(BaseCommand):
    help = "Vérifie la cohérence entre ai_credits et le registre des crédits."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Crée les écritures d'ouverture manquantes pour aligner le registre.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Nombre d'écarts détaillés à afficher (défaut : 20).",
        )

    def handle(self, *args, **options):
        users = User.objects.annotate(ledger=Sum("credit_entries__delta"))

        drifts = []
        for user in users.iterator(chunk_size=500):
            ledger = user.ledger or 0
            balance = user.ai_credits or 0
            if ledger != balance:
                drifts.append((user, balance, ledger, balance - ledger))

        total = users.count()
        if not drifts:
            self.stdout.write(self.style.SUCCESS(
                f"Registre cohérent : {total} compte(s) vérifié(s), aucun écart."
            ))
            return

        self.stdout.write(self.style.WARNING(
            f"{len(drifts)} compte(s) sur {total} présentent un écart."
        ))
        self.stdout.write("")
        self.stdout.write(f"  {'compte':<40} {'solde':>8} {'registre':>10} {'écart':>8}")
        for user, balance, ledger, gap in drifts[: options["limit"]]:
            self.stdout.write(f"  {user.email[:38]:<40} {balance:>8} {ledger:>10} {gap:>+8}")
        if len(drifts) > options["limit"]:
            self.stdout.write(f"  … et {len(drifts) - options['limit']} autre(s).")
        self.stdout.write("")

        if not options["fix"]:
            self.stdout.write(
                "Relancez avec --fix pour créer les écritures d'ouverture manquantes."
            )
            return

        entries = [
            CreditEntry(
                user=user,
                delta=gap,
                reason=CreditEntry.Reason.ADMIN_GRANT,
                operation="reconciliation",
                note="Solde d'ouverture, antérieur à la mise en place du registre",
                balance_after=balance,
            )
            for user, balance, ledger, gap in drifts
            if gap != 0  # la contrainte en base interdit une écriture nulle
        ]
        CreditEntry.objects.bulk_create(entries, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f"{len(entries)} écriture(s) d'ouverture créée(s). "
            "Le registre et les soldes concordent désormais."
        ))
