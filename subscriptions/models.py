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
