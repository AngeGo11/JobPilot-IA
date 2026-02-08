from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class SubscriptionPlan(models.TextChoices):
    PASS24H = "pass24h", "Pass 24h"
    SPRINT = "sprint", "Sprint"
    PRO = "pro", "Pro"

class CustomUser(AbstractUser):
    """
    On utilise notre propre classe User pour pouvoir ajouter des champs plus tard
    (ex: is_recruiter, is_candidate) si besoin.
    Modèle hybride : crédits IA + abonnement premium.
    """
    ai_credits = models.IntegerField("Crédits IA", default=3)
    subscription_end_date = models.DateTimeField("Fin d'abonnement", null=True, blank=True)
    subscription_plan = models.CharField(
        "Type d'abonnement",
        max_length=20,
        choices=SubscriptionPlan.choices,
        null=True,
        blank=True,
    )

    @property
    def is_premium(self):
        """True si l'utilisateur a un abonnement actif (date de fin dans le futur)."""
        if not self.subscription_end_date:
            return False
        return self.subscription_end_date > timezone.now()

    @property
    def can_generate(self):
        """True si l'utilisateur peut utiliser les outils IA (premium ou crédits > 0)."""
        return self.is_premium or (self.ai_credits and self.ai_credits > 0)


class CandidateProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile') #OneToOneField est la relation 1-à-1 entre deux tables
    phone = models.CharField("Téléphone", max_length=20, blank=True)
    location = models.CharField("Ville/Code Postal", max_length=100, blank=True)

    # Le code ROME est le code métier de France Travail (ex: M1805)
    # On le stocke ici si le candidat a un métier cible précis.
    target_rome_code = models.CharField("Code ROME Cible", max_length=10, blank=True, null=True)

    # Disponibilité
    is_available = models.BooleanField("En recherche active", default=True)

    def __str__(self):
        return f"Profil de {self.user.username}"