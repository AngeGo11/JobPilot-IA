from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings


class Resume(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resumes')
    title = models.CharField("Titre du CV", max_length=100, default="Mon CV")
    file = models.FileField(
        "Fichier PDF",
        upload_to='cvs/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Est-ce le CV principal utilisé pour les recherches automatiques ?
    is_primary = models.BooleanField(default=False)

    # --- PARTIE ANALYSE (POSTGRESQL) ---

    # Contenu brut extrait du PDF (pour la recherche full-text plus tard)
    extracted_text = models.TextField("Texte extrait", blank=True)

    # Titre du poste visé détecté par l'IA (ex: "Stage Data Engineer", "Alternance Développeur Java")
    detected_job_title = models.CharField("Titre du poste visé", max_length=255, null=True, blank=True)

    # Compétences techniques détectées par l'IA (ex: ["Python", "Django", "Docker"])
    detected_skills = models.JSONField("Compétences détectées", default=list, blank=True)

    # Compétences détectées stockées en JSON (ex: ["Python", "Django", "Docker"])
    # C'est ici que PostgreSQL est super fort : tu pourras faire des requêtes directes sur ce JSON.
    parsed_skills = models.JSONField("Compétences détectées (legacy)", default=list, blank=True)

    # Infos extraites (ex: {"years_exp": 3, "level": "Junior"})
    parsed_data = models.JSONField("Métadonnées IA", default=dict, blank=True)

    def __str__(self):
        return f"{self.title} ({self.user.email})"


@receiver(post_delete, sender=Resume)
def delete_resume_file_on_delete(sender, instance, **kwargs):
    """
    RGPD (art. 17 - droit à l'effacement) : Django ne supprime PAS le fichier
    physique du storage lors d'un `.delete()` du modèle. Sans ce signal, le PDF
    du candidat (donnée personnelle) resterait sur le disque/cloud après la
    suppression de l'enregistrement en base. On efface donc le fichier réel.
    Fonctionne aussi lors des suppressions en cascade (ex. suppression du compte
    utilisateur) car post_delete est émis pour chaque instance supprimée.
    """
    if instance.file:
        instance.file.delete(save=False)