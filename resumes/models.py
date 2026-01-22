from django.db import models
from django.conf import settings


class Resume(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resumes')
    title = models.CharField("Titre du CV", max_length=100, default="Mon CV")
    file = models.FileField("Fichier PDF", upload_to='cvs/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Est-ce le CV principal utilisé pour les recherches automatiques ?
    is_primary = models.BooleanField(default=False)

    # --- PARTIE ANALYSE (POSTGRESQL) ---

    # Contenu brut extrait du PDF (pour la recherche full-text plus tard)
    extracted_text = models.TextField("Texte extrait", blank=True)

    # Compétences détectées stockées en JSON (ex: ["Python", "Django", "Docker"])
    # C'est ici que PostgreSQL est super fort : tu pourras faire des requêtes directes sur ce JSON.
    parsed_skills = models.JSONField("Compétences détectées", default=list, blank=True)

    # Infos extraites (ex: {"years_exp": 3, "level": "Junior"})
    parsed_data = models.JSONField("Métadonnées IA", default=dict, blank=True)

    def __str__(self):
        return f"{self.title} ({self.user.username})"