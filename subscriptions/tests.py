"""Tests du registre de crédits."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from subscriptions.models import CreditEntry, Transaction
from subscriptions.services.credits import (
    InsufficientCredits,
    debit,
    grant,
    ledger_balance,
    refund,
)

User = get_user_model()


class DebitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        self.user.ai_credits = 3
        self.user.save(update_fields=["ai_credits"])

    def test_debit_decrements_and_records(self):
        entry = debit(self.user, operation="generate_letter")
        self.user.refresh_from_db()

        self.assertEqual(self.user.ai_credits, 2)
        self.assertEqual(entry.delta, -1)
        self.assertEqual(entry.operation, "generate_letter")
        self.assertEqual(entry.reason, CreditEntry.Reason.CONSUMPTION)
        self.assertEqual(entry.balance_after, 2)

    def test_debit_raises_when_empty(self):
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])

        with self.assertRaises(InsufficientCredits):
            debit(self.user, operation="generate_letter")

        # Aucune écriture parasite ne doit rester derrière un débit refusé.
        self.assertEqual(CreditEntry.objects.count(), 0)

    def test_premium_user_is_not_debited(self):
        self.user.subscription_end_date = timezone.now() + timedelta(days=5)
        self.user.save(update_fields=["subscription_end_date"])

        self.assertIsNone(debit(self.user, operation="generate_letter"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 3)
        self.assertEqual(CreditEntry.objects.count(), 0)


class RefundTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        self.user.ai_credits = 3
        self.user.save(update_fields=["ai_credits"])

    def test_refund_restores_balance_and_links_entries(self):
        entry = debit(self.user, operation="optimize_cv")
        reversal = refund(entry, note="API indisponible")
        self.user.refresh_from_db()

        self.assertEqual(self.user.ai_credits, 3)
        self.assertEqual(reversal.delta, 1)
        self.assertEqual(reversal.reverses, entry)
        self.assertEqual(reversal.reason, CreditEntry.Reason.REFUND)
        self.assertTrue(entry.is_reversed)

    def test_double_refund_is_ignored(self):
        """
        Le point critique : l'ancien code appelait refund_credit dans des blocs
        `except` imbriqués, ce qui pouvait créditer deux fois pour un seul débit.
        """
        entry = debit(self.user, operation="optimize_cv")
        refund(entry)
        second = refund(entry)

        self.user.refresh_from_db()
        self.assertIsNone(second)
        self.assertEqual(self.user.ai_credits, 3)
        self.assertEqual(CreditEntry.objects.filter(reason=CreditEntry.Reason.REFUND).count(), 1)

    def test_refund_of_none_is_a_noop(self):
        """Un abonné premium n'a pas d'écriture à rembourser."""
        self.assertIsNone(refund(None))
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 3)


class GrantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        self.user.ai_credits = 2
        self.user.save(update_fields=["ai_credits"])

    def test_grant_adds_credits(self):
        entry = grant(self.user, 10, reason=CreditEntry.Reason.PURCHASE, note="Pack 10")
        self.user.refresh_from_db()

        self.assertEqual(self.user.ai_credits, 12)
        self.assertEqual(entry.delta, 10)
        self.assertEqual(entry.balance_after, 12)

    def test_negative_grant_never_produces_a_negative_balance(self):
        grant(self.user, -50, reason=CreditEntry.Reason.ADMIN_GRANT, note="correction")
        self.user.refresh_from_db()
        self.assertEqual(self.user.ai_credits, 0)

    def test_zero_grant_is_ignored(self):
        self.assertIsNone(grant(self.user, 0, reason=CreditEntry.Reason.ADMIN_GRANT))
        self.assertEqual(CreditEntry.objects.count(), 0)


class LedgerConsistencyTests(TestCase):
    def test_ledger_matches_balance_after_a_sequence(self):
        """
        Le registre rejoué doit donner le même solde que `ai_credits`.
        C'est l'invariant qui rend le registre utile : s'il diverge, c'est
        qu'une mutation est passée à côté du service.
        """
        user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        user.ai_credits = 0
        user.save(update_fields=["ai_credits"])

        grant(user, 5, reason=CreditEntry.Reason.SIGNUP)
        first = debit(user, operation="generate_letter")
        debit(user, operation="optimize_cv")
        refund(first, note="échec")
        grant(user, 10, reason=CreditEntry.Reason.PURCHASE)

        user.refresh_from_db()
        self.assertEqual(user.ai_credits, 14)
        self.assertEqual(ledger_balance(user), 14)


class TestModeExclusionTests(TestCase):
    """
    Les paiements du bac à sable Stripe ne doivent jamais entrer dans le
    chiffre d'affaires. Constaté en production : sur cinq transactions, trois
    étaient des tests — le total affiché valait 21,96 € pour 5,99 € réels.
    """

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal as D

        cls.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        # Trois paiements de mise au point, deux vrais.
        for suffixe, montant in (("a", D("4.99")), ("b", D("4.99")), ("c", D("5.99"))):
            Transaction.objects.create(
                user=cls.user, stripe_session_id=f"cs_test_{suffixe}", amount=montant
            )
        for suffixe, montant in (("x", D("1.00")), ("y", D("4.99"))):
            Transaction.objects.create(
                user=cls.user, stripe_session_id=f"cs_live_{suffixe}", amount=montant
            )

    def test_is_test_mode_detects_sandbox_sessions(self):
        self.assertTrue(Transaction.objects.get(stripe_session_id="cs_test_a").is_test_mode)
        self.assertFalse(Transaction.objects.get(stripe_session_id="cs_live_x").is_test_mode)

    def test_revenue_counts_only_real_payments(self):
        from decimal import Decimal as D

        from administration.services.metrics import revenue_metrics

        stats = revenue_metrics()
        self.assertEqual(stats["total"], D("5.99"), "1,00 + 4,99 seulement")
        self.assertEqual(stats["count"], 2)
        # Le volume de test est rapporté à part, pas effacé : le voir évite de
        # croire à une perte de données.
        self.assertEqual(stats["test_count"], 3)
        self.assertEqual(stats["test_total"], D("15.97"))

    def test_average_basket_ignores_test_payments(self):
        from decimal import Decimal as D

        from administration.services.metrics import revenue_metrics

        # Moyenne sur les deux vrais paiements : (1,00 + 4,99) / 2 = 2,995
        self.assertAlmostEqual(float(revenue_metrics()["avg_basket"]), 2.995, places=2)

    def test_monthly_chart_excludes_test_payments(self):
        from administration.views import monthly_revenue

        total = sum(row["total"] for row in monthly_revenue())
        self.assertEqual(float(total), 5.99)
