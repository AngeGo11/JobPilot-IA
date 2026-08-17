from django.db import models
from django.conf import settings
from pgvector.django import HnswIndex, VectorField

from matching.services.embeddings import EMBEDDING_DIMENSIONS
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

    # --- Matching sémantique ---
    embedding = VectorField(
        "Vecteur sémantique",
        dimensions=EMBEDDING_DIMENSIONS,
        null=True,
        blank=True,
    )
    embedding_fingerprint = models.CharField(
        "Empreinte du texte vectorisé",
        max_length=64,
        blank=True,
        help_text="Évite de recalculer le vecteur quand le contenu n'a pas changé.",
    )
    embedded_at = models.DateTimeField("Vectorisée le", null=True, blank=True)

    class Meta:
        indexes = [
            # Le back-office et les alertes trient les offres par date d'ingestion.
            models.Index(fields=["-created_at"], name="joboffer_created_idx"),
            models.Index(fields=["-date_posted"], name="joboffer_posted_idx"),
            # Index approximatif HNSW : une recherche par similarité sans index
            # compare le vecteur cible à toutes les lignes de la table.
            HnswIndex(
                name="joboffer_embedding_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

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

    # Verrouillage : False = offre trouvée mais pas encore "achetée" par 1 crédit
    is_unlocked = models.BooleanField("Déblocage (crédit consommé)", default=False)

    # Lettre de motivation (brouillon)
    cover_letter_content = models.TextField("Lettre de motivation", blank=True)

    # Score sémantique, calculé en parallèle de `score` (mots-clés) pendant la
    # période de comparaison. `None` tant que les deux vecteurs ne sont pas
    # disponibles. Voir SiteSettings.semantic_matching_enabled pour savoir
    # lequel des deux pilote réellement l'affichage.
    semantic_score = models.IntegerField(
        "Score sémantique", null=True, blank=True
    )

    @property
    def display_score(self):
        """
        Score montré au candidat.

        Passe par `SiteSettings.semantic_matching_enabled` : tant que la bascule
        n'est pas faite, c'est le score par mots-clés qui s'affiche, même quand
        le score sémantique existe déjà.
        """
        from matching.services.scoring import effective_score

        return effective_score(self)

    class Meta:
        # Un CV ne peut avoir qu'un seul "Match" pour une même offre
        # Cela permet à un utilisateur d'avoir plusieurs matches pour la même offre avec des CVs différents
        unique_together = ('resume', 'job_offer')
        ordering = ['-score']  # Les meilleurs scores en premier
        indexes = [
            # Requête du dashboard : offres débloquées d'un utilisateur, triées
            # par score. Sans cet index, PostgreSQL parcourt toute la table et
            # trie en mémoire dès que le volume dépasse quelques milliers de lignes.
            models.Index(
                fields=["user", "is_unlocked", "-score"],
                name="jobmatch_user_unlocked_idx",
            ),
            # Écran de résultats d'un CV donné.
            models.Index(fields=["resume", "is_unlocked"], name="jobmatch_resume_idx"),
            # Statistiques du back-office (répartition par statut, volumétrie 7 j).
            models.Index(fields=["status", "-matched_at"], name="jobmatch_status_idx"),
        ]


class JobAlert(models.Model):
    """
    Alerte : notifier l'utilisateur par email lorsqu'une nouvelle offre correspondant à son CV est détectée.
    Basé sur le CV (resume) et le titre de poste détecté (resume.detected_job_title).
    """
    resume = models.ForeignKey(
        Resume,
        on_delete=models.CASCADE,
        related_name='job_alerts'
    )
    is_active = models.BooleanField("Actif", default=True)
    last_checked = models.DateTimeField("Dernière vérification", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Un CV ne peut avoir qu'une alerte active à la fois (on peut réutiliser le même en activant/désactivant)
        unique_together = ('resume',)
        ordering = ['-created_at']

    def __str__(self):
        return f"Alerte pour {self.resume.title} (actif={self.is_active})"

class AIJob(models.Model):
    """
    Suivi d'un traitement IA exécuté en tâche de fond.

    Deux raisons d'exister plutôt que de s'appuyer sur le seul identifiant de
    tâche Celery :

    1. **Autorisation.** Le navigateur interroge l'état via l'identifiant de
       tâche. Sans propriétaire enregistré, il suffirait de connaître un
       identifiant pour lire la lettre de motivation d'un autre candidat.
       L'identifiant est un UUID, donc difficile à deviner — mais « difficile à
       deviner » n'est pas un contrôle d'accès.
    2. **Supervision.** Le back-office peut afficher les traitements en cours,
       leur durée et leurs échecs, ce que le backend de résultats Celery ne
       conserve que 24 h.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        RUNNING = "running", "En cours"
        SUCCESS = "success", "Terminé"
        FAILURE = "failure", "Échec"

    task_id = models.CharField("Identifiant de tâche", max_length=255, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_jobs",
        verbose_name="Utilisateur",
    )
    operation = models.CharField("Opération", max_length=50)
    status = models.CharField(
        "Statut", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    job_match = models.ForeignKey(
        "matching.JobMatch",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_jobs",
        verbose_name="Candidature concernée",
    )
    credit_entry = models.ForeignKey(
        "subscriptions.CreditEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_jobs",
        verbose_name="Écriture de crédit",
        help_text="Débit associé, remboursé automatiquement si la tâche échoue.",
    )
    result = models.JSONField("Résultat", default=dict, blank=True)
    error = models.TextField("Message d'erreur", blank=True)
    error_status = models.PositiveSmallIntegerField(
        "Code HTTP équivalent", null=True, blank=True
    )
    created_at = models.DateTimeField("Création", auto_now_add=True)
    started_at = models.DateTimeField("Début", null=True, blank=True)
    finished_at = models.DateTimeField("Fin", null=True, blank=True)

    class Meta:
        verbose_name = "Traitement IA"
        verbose_name_plural = "Traitements IA"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="aijob_user_idx"),
            models.Index(fields=["status", "-created_at"], name="aijob_status_idx"),
        ]

    def __str__(self):
        return f"{self.operation} – {self.get_status_display()}"

    @property
    def is_finished(self):
        return self.status in (self.Status.SUCCESS, self.Status.FAILURE)

    @property
    def duration_seconds(self):
        if not (self.started_at and self.finished_at):
            return None
        return (self.finished_at - self.started_at).total_seconds()
