from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    """
    On utilise notre propre classe User pour pouvoir ajouter des champs plus tard
    (ex: is_recruiter, is_candidate) si besoin.
    """
    pass


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