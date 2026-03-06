from django.conf import settings
from django.db import models


class StripeSubscription(models.Model):
    """
    Lie un abonnement Stripe à un utilisateur pour mettre à jour
    subscription_end_date à chaque renouvellement (webhook).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stripe_subscription'
    )
    stripe_subscription_id = models.CharField("ID abonnement Stripe", max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonnement Stripe"
        verbose_name_plural = "Abonnements Stripe"

    def __str__(self):
        return f"{self.user} – {self.stripe_subscription_id}"


class Transaction(models.Model):
    """
    Traçabilité des paiements Stripe pour l'idempotence des webhooks.
    Une entrée par session Checkout traitée (session_id unique) évite les doubles
    ajouts de crédits ou d'abonnements lors des retries Stripe.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stripe_transactions'
    )
    stripe_session_id = models.CharField("ID session Stripe", max_length=255, unique=True)
    amount = models.DecimalField(
        "Montant (€)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Montant payé (optionnel, depuis session.amount_total)",
    )
    created_at = models.DateTimeField("Date de traitement", auto_now_add=True)

    class Meta:
        verbose_name = "Transaction Stripe"
        verbose_name_plural = "Transactions Stripe"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_id} – {self.stripe_session_id}"
