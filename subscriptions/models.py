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

    # Préfixe des sessions Stripe créées en mode bac à sable. Les paiements de
    # mise au point cohabitent avec les vrais dans cette table : additionner
    # les deux gonfle artificiellement le chiffre d'affaires — d'un facteur
    # trois sur les premières semaines d'un produit.
    TEST_SESSION_PREFIX = "cs_test"

    @property
    def is_test_mode(self):
        """True pour un paiement effectué en mode test : argent inexistant."""
        return (self.stripe_session_id or "").startswith(self.TEST_SESSION_PREFIX)

    def __str__(self):
        return f"{self.user_id} – {self.stripe_session_id}"


class CreditEntry(models.Model):
    """
    Registre des mouvements de crédits IA, en écriture seule.

    Pourquoi : `CustomUser.ai_credits` est un simple entier que quatre endroits
    modifient. Quand un utilisateur signale « j'ai perdu un crédit », rien ne
    permet de vérifier. Pire : le motif « débiter → appeler l'IA → rembourser en
    cas d'échec » perd définitivement le crédit si le processus meurt entre les
    deux étapes, sans laisser de trace.

    Chaque mouvement est donc écrit ici, dans la même transaction que la mise à
    jour du solde. `ai_credits` reste le solde rapide utilisé par l'application ;
    ce registre en est l'historique vérifiable. La commande
    `reconcile_credits` compare les deux et signale toute dérive.
    """

    class Reason(models.TextChoices):
        SIGNUP = "signup", "Crédits offerts à l'inscription"
        PURCHASE = "purchase", "Achat"
        ADMIN_GRANT = "admin_grant", "Ajustement par l'équipe"
        CONSUMPTION = "consumption", "Consommation"
        REFUND = "refund", "Remboursement après échec"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credit_entries",
        verbose_name="Utilisateur",
    )
    delta = models.IntegerField(
        "Mouvement",
        help_text="Négatif pour une consommation, positif pour un ajout.",
    )
    reason = models.CharField("Motif", max_length=20, choices=Reason.choices)
    operation = models.CharField(
        "Opération",
        max_length=50,
        blank=True,
        help_text="Action à l'origine du mouvement (ex. « generate_letter »).",
    )
    reverses = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversals",
        verbose_name="Annule l'écriture",
        help_text="Renseigné sur un remboursement : pointe la consommation annulée.",
    )
    note = models.CharField("Précision", max_length=255, blank=True)
    balance_after = models.IntegerField(
        "Solde après écriture",
        null=True,
        blank=True,
        help_text="Photographie du solde, pour repérer une dérive sans rejouer tout l'historique.",
    )
    created_at = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        verbose_name = "Mouvement de crédit"
        verbose_name_plural = "Registre des crédits"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="creditentry_user_idx"),
            models.Index(fields=["reason", "-created_at"], name="creditentry_reason_idx"),
        ]
        constraints = [
            # Une écriture à zéro n'a aucun sens et masquerait un bug d'appelant.
            models.CheckConstraint(condition=~models.Q(delta=0), name="creditentry_delta_non_nul"),
        ]

    def __str__(self):
        sign = "+" if self.delta > 0 else ""
        return f"{self.user_id} : {sign}{self.delta} ({self.get_reason_display()})"

    @property
    def is_reversed(self):
        """True si cette consommation a déjà été remboursée."""
        return self.reversals.exists()
