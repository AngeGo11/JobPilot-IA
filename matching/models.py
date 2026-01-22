from django.db import models
from django.conf import settings

from resumes.models import Resume


class JobOffer(models.Model):
    """
    Stocke une offre récupérée depuis l'API pour éviter de la redemander à chaque fois.
    """
    # L'ID unique de France Travail
    remote_id = models.CharField("ID France Travail", max_length=50, unique=True)

    title = models.CharField("Intitulé du poste", max_length=255)
    company_name = models.CharField("Entreprise", max_length=255, blank=True)
    description = models.TextField("Description", blank=True)

    # URL pour postuler
    url = models.URLField("Lien offre", max_length=500, blank=True)

    location = models.CharField("Lieu", max_length=100, blank=True)
    contract_type = models.CharField("Type de contrat", max_length=50, blank=True)  # CDI, CDD...

    date_posted = models.DateTimeField("Date de publication", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # On garde tout le JSON brut de l'API au cas où on veut afficher un détail oublié
    raw_api_data = models.JSONField("Données brutes API", default=dict)

    def __str__(self):
        return f"{self.title} chez {self.company_name}"


class JobMatch(models.Model):
    """
    Table de liaison : Pour dire "Ce CV matche avec Cette Offre à 85%"
    """
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='matches', null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job_offer = models.ForeignKey(JobOffer, on_delete=models.CASCADE)

    # Score de pertinence calculé par ton algo (de 0 à 100)
    score = models.IntegerField("Score de matching", default=0)

    # État de la candidature
    STATUS_CHOICES = [
        ('new', 'Nouveau match'),
        ('seen', 'Vu'),
        ('applied', 'Postulé'),
        ('rejected', 'Rejeté par candidat'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    matched_at = models.DateTimeField(auto_now_add=True)
    
    # Lettre de motivation (brouillon)
    cover_letter_content = models.TextField("Lettre de motivation", blank=True)

    class Meta:
        # Un utilisateur ne peut avoir qu'un seul "Match" pour une même offre
        unique_together = ('user', 'job_offer')
        ordering = ['-score']  # Les meilleurs scores en premier