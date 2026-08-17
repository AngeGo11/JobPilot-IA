"""
Tests de la couche `use_cases` du domaine matching.

Ce qui est vérifié ici est précisément ce que l'ancien code ne garantissait
pas : quel que soit le mode d'échec, l'utilisateur ne perd pas son crédit, et
il n'en gagne pas non plus.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from matching.use_cases import AIOperation, AIOperationError, InsufficientCredits
from subscriptions.models import CreditEntry
from subscriptions.services.credits import grant, ledger_balance
from utils.gemini_safe import FairUseExceeded, GeminiServiceUnavailable

User = get_user_model()


# DEBUG=False : en développement, AIOperation laisse volontairement remonter
# les erreurs inattendues pour ne pas masquer un bug derrière un message poli.
@override_settings(DEBUG=False)
class AIOperationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        # Crédits initiaux posés via le service : écrire `ai_credits` en direct
        # créerait précisément la dérive que le registre sert à détecter.
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])
        grant(self.user, 3, reason=CreditEntry.Reason.SIGNUP)

    def _balance(self):
        self.user.refresh_from_db()
        return self.user.ai_credits

    # --- Chemin nominal ---------------------------------------------------

    def test_success_consumes_exactly_one_credit(self):
        result = AIOperation("generate_letter").run(self.user, lambda: "lettre générée")

        self.assertEqual(result, "lettre générée")
        self.assertEqual(self._balance(), 2)
        self.assertEqual(CreditEntry.objects.filter(delta=-1).count(), 1)
        self.assertEqual(ledger_balance(self.user), 2)

    def test_free_operation_consumes_nothing(self):
        """L'export PDF n'appelle aucun modèle : il ne doit rien facturer."""
        result = AIOperation("export_pdf", free=True).run(self.user, lambda: b"%PDF")

        self.assertEqual(result, b"%PDF")
        self.assertEqual(self._balance(), 3)
        # Seule l'écriture d'ouverture existe : rien n'a été facturé.
        self.assertEqual(CreditEntry.objects.count(), 1)

    def test_premium_user_is_not_charged(self):
        self.user.subscription_end_date = timezone.now() + timedelta(days=10)
        self.user.save(update_fields=["subscription_end_date"])

        AIOperation("generate_letter").run(self.user, lambda: "ok")

        self.assertEqual(self._balance(), 3)
        self.assertEqual(CreditEntry.objects.count(), 1)  # l'ouverture seule

    # --- Solde vide -------------------------------------------------------

    def test_empty_balance_raises_before_calling_the_action(self):
        self.user.ai_credits = 0
        self.user.save(update_fields=["ai_credits"])
        called = []

        with self.assertRaises(InsufficientCredits):
            AIOperation("generate_letter").run(self.user, lambda: called.append(1))

        # L'action ne doit pas être exécutée : un appel Gemini non facturé
        # coûterait du quota pour rien.
        self.assertEqual(called, [])

    # --- Modes d'échec ----------------------------------------------------

    def _assert_refunded(self, exception, expected_status):
        def failing():
            raise exception

        with self.assertRaises(AIOperationError) as ctx:
            AIOperation("generate_letter").run(self.user, failing)

        self.assertEqual(ctx.exception.status, expected_status)
        self.assertEqual(self._balance(), 3, "le crédit doit avoir été remboursé")
        self.assertEqual(ledger_balance(self.user), 3)
        # Ouverture + consommation + remboursement, tous tracés.
        self.assertEqual(CreditEntry.objects.count(), 3)

    def test_fair_use_refunds(self):
        self._assert_refunded(FairUseExceeded("quota"), 429)

    def test_service_unavailable_refunds(self):
        self._assert_refunded(GeminiServiceUnavailable("surcharge"), 503)

    def test_client_disconnect_refunds(self):
        self._assert_refunded(BrokenPipeError("client parti"), 499)

    def test_validation_error_refunds(self):
        self._assert_refunded(ValueError("texte vide"), 400)

    def test_unexpected_error_refunds(self):
        self._assert_refunded(RuntimeError("panne imprévue"), 503)

    def test_refund_happens_once_per_failure(self):
        """
        Deux échecs successifs laissent exactement deux consommations et deux
        remboursements — pas de crédit créé au passage.
        """
        for _ in range(2):
            with self.assertRaises(AIOperationError):
                AIOperation("optimize_cv").run(
                    self.user, lambda: (_ for _ in ()).throw(GeminiServiceUnavailable())
                )

        self.assertEqual(self._balance(), 3)
        self.assertEqual(CreditEntry.objects.filter(delta=-1).count(), 2)
        self.assertEqual(CreditEntry.objects.filter(delta=1).count(), 2)


@override_settings(DEBUG=True)
class DebugModeTests(TestCase):
    def test_unexpected_errors_surface_in_development(self):
        """
        En développement, masquer une erreur inattendue derrière « serveurs
        surchargés » rend le débogage impossible. Le crédit est tout de même
        remboursé avant que l'erreur ne remonte.
        """
        user = User.objects.create_user(email="d@example.com", password="MotDePasse!2024")
        user.ai_credits = 0
        user.save(update_fields=["ai_credits"])
        grant(user, 2, reason=CreditEntry.Reason.SIGNUP)

        def failing():
            raise RuntimeError("erreur de programmation")

        with self.assertRaises(RuntimeError):
            AIOperation("generate_letter").run(user, failing)

        user.refresh_from_db()
        self.assertEqual(user.ai_credits, 2)
