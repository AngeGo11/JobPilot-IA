from django.conf import settings
from django.core.cache import cache
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


SITE_SETTINGS_CACHE_KEY = "administration:site_settings"
SITE_SETTINGS_CACHE_TTL = 300  # 5 minutes


class SiteSettings(models.Model):
    """
    Réglages généraux de la plateforme, éditables depuis le back-office.

    Singleton : une seule ligne (pk=1). On passe systématiquement par
    `SiteSettings.load()` qui met le résultat en cache pour éviter un accès base
    à chaque requête (le middleware de maintenance le lit sur toutes les vues).
    """

    # --- Disponibilité du site ---
    maintenance_mode = models.BooleanField(
        "Mode maintenance",
        default=False,
        help_text="Coupe l'accès au site pour tout le monde sauf l'équipe (is_staff).",
    )
    maintenance_message = models.TextField(
        "Message de maintenance",
        blank=True,
        default="JobPilot-AI est en maintenance. Nous revenons très vite.",
    )
    registrations_open = models.BooleanField(
        "Inscriptions ouvertes",
        default=True,
        help_text="Si décoché, la page d'inscription refuse les nouveaux comptes.",
    )

    # --- Quotas et règles métier ---
    signup_free_credits = models.PositiveIntegerField(
        "Crédits IA offerts à l'inscription",
        default=5,
        validators=[MaxValueValidator(1000)],
    )
    max_resumes_per_user = models.PositiveIntegerField(
        "Nombre de CV maximum par utilisateur",
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    matching_min_score = models.PositiveIntegerField(
        "Score de matching minimum (%)",
        default=70,
        validators=[MaxValueValidator(100)],
        help_text="Seuil en dessous duquel une offre n'est pas proposée au candidat.",
    )
    semantic_matching_enabled = models.BooleanField(
        "Matching sémantique actif",
        default=False,
        help_text=(
            "Décoché : le score par mots-clés pilote l'affichage, le score "
            "sémantique est calculé en parallèle sans être montré. Cochez une "
            "fois la comparaison des deux scores jugée concluante."
        ),
    )

    # --- Alertes emails ---
    alerts_enabled = models.BooleanField(
        "Alertes nouvelles offres activées",
        default=True,
        help_text="Coupe globalement l'envoi des emails de `check_new_offers`.",
    )
    alerts_max_offers_per_email = models.PositiveIntegerField(
        "Nombre d'offres maximum par email d'alerte",
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
    )

    # --- Contact ---
    contact_email = models.EmailField(
        "Email de contact affiché",
        blank=True,
        default="",
    )
    support_notice = models.CharField(
        "Bandeau d'information (public)",
        max_length=255,
        blank=True,
        default="",
        help_text="Laisser vide pour ne rien afficher aux utilisateurs.",
    )

    # --- Traçabilité ---
    updated_at = models.DateTimeField("Dernière modification", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Modifié par",
    )

    class Meta:
        verbose_name = "Paramètres du site"
        verbose_name_plural = "Paramètres du site"

    def __str__(self):
        return "Paramètres du site"

    def save(self, *args, **kwargs):
        self.pk = 1  # force le singleton
        super().save(*args, **kwargs)
        cache.delete(SITE_SETTINGS_CACHE_KEY)

    def delete(self, *args, **kwargs):  # pragma: no cover - sécurité
        raise RuntimeError("Les paramètres du site ne peuvent pas être supprimés.")

    @classmethod
    def load(cls):
        """Retourne l'unique instance, en la créant au premier appel. Mise en cache."""
        cached = cache.get(SITE_SETTINGS_CACHE_KEY)
        if cached is not None:
            return cached
        obj, _ = cls.objects.get_or_create(pk=1)
        cache.set(SITE_SETTINGS_CACHE_KEY, obj, SITE_SETTINGS_CACHE_TTL)
        return obj


class AdminAuditLog(models.Model):
    """
    Journal des actions sensibles réalisées depuis le back-office.

    Sert à répondre à « qui a changé quoi, quand » — utile en cas d'incident et
    attendu par le RGPD (art. 32) pour tout accès à des données personnelles.
    """

    class Action(models.TextChoices):
        SETTINGS_UPDATED = "settings_updated", "Paramètres modifiés"
        USER_VIEWED = "user_viewed", "Fiche utilisateur consultée"
        USER_DEACTIVATED = "user_deactivated", "Utilisateur désactivé"
        USER_REACTIVATED = "user_reactivated", "Utilisateur réactivé"
        CREDITS_GRANTED = "credits_granted", "Crédits accordés"
        SUBSCRIPTION_EXTENDED = "subscription_extended", "Abonnement prolongé"
        ALERT_TOGGLED = "alert_toggled", "Alerte activée/désactivée"
        EXPORT_RUN = "export_run", "Export de données"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="admin_actions",
        verbose_name="Administrateur",
    )
    action = models.CharField("Action", max_length=40, choices=Action.choices)
    target = models.CharField(
        "Cible",
        max_length=255,
        blank=True,
        help_text="Libellé de l'objet concerné (ex. « utilisateur #42 »).",
    )
    details = models.JSONField("Détails", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("Adresse IP", null=True, blank=True)
    created_at = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        verbose_name = "Entrée du journal d'audit"
        verbose_name_plural = "Journal d'audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%d/%m/%Y %H:%M} – {self.get_action_display()}"


class TaskRun(models.Model):
    """
    Trace d'exécution des tâches planifiées (`check_new_offers`, etc.).

    Sans ça, une tâche cron qui cesse silencieusement de tourner est invisible :
    la page de supervision compare la dernière exécution à la fréquence attendue
    pour lever une alerte.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "En cours"
        SUCCESS = "success", "Succès"
        ERROR = "error", "Échec"

    name = models.CharField("Commande", max_length=100, db_index=True)
    status = models.CharField(
        "Statut", max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    started_at = models.DateTimeField("Début", default=timezone.now)
    finished_at = models.DateTimeField("Fin", null=True, blank=True)
    items_processed = models.IntegerField("Éléments traités", default=0)
    message = models.TextField("Message / erreur", blank=True)

    class Meta:
        verbose_name = "Exécution de tâche"
        verbose_name_plural = "Exécutions de tâches"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["name", "-started_at"])]

    def __str__(self):
        return f"{self.name} – {self.get_status_display()}"

    @property
    def duration_seconds(self):
        if not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()


class Testimonial(models.Model):
    """
    Témoignage client affiché sur la page d'accueil.

    Pourquoi un modèle plutôt que du texte en dur dans le gabarit : un
    témoignage engage juridiquement. Publier un avis inventé ou embelli est une
    pratique commerciale trompeuse (art. L121-2 du code de la consommation), et
    la personne citée doit avoir donné son accord — d'où le champ
    `consent_reference`, qui garde la trace de cet accord.

    La section n'apparaît sur l'accueil que s'il existe au moins une entrée
    publiée : tant que l'équipe n'a pas recueilli de vrais retours, le site ne
    montre rien plutôt qu'un placeholder.
    """

    author_name = models.CharField(
        "Nom affiché", max_length=80,
        help_text="Tel qu'accepté par la personne, par exemple « Lucas B. ».",
    )
    author_role = models.CharField(
        "Poste / situation", max_length=120,
        help_text="Par exemple « Développeur full-stack, recruté en mars 2026 ».",
    )
    quote = models.TextField(
        "Témoignage",
        help_text="Citation littérale. Ne pas reformuler à la place de la personne.",
    )
    result_metric = models.CharField(
        "Résultat mesurable", max_length=120, blank=True,
        help_text="Chiffre vérifiable issu du témoignage : « 3 entretiens en 2 semaines ».",
    )
    consent_reference = models.CharField(
        "Preuve d'accord", max_length=200,
        help_text="Où retrouver l'accord écrit : date et objet du mail, lien, référence interne.",
    )
    is_published = models.BooleanField(
        "Publié", default=False,
        help_text="Décoché tant que l'accord n'est pas obtenu et vérifié.",
    )
    display_order = models.PositiveIntegerField("Ordre d'affichage", default=0)
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        verbose_name = "Témoignage client"
        verbose_name_plural = "Témoignages clients"
        ordering = ["display_order", "-created_at"]

    def __str__(self):
        return f"{self.author_name} – {'publié' if self.is_published else 'brouillon'}"


class ErrorLog(models.Model):
    """
    Erreurs applicatives, enregistrées en base.

    Pourquoi pas un fichier : en production, `LOGGING` bascule sur la sortie
    standard car App Service n'offre pas de répertoire inscriptible fiable. Le
    panneau de supervision n'avait donc rien à lire et affichait un message
    d'excuse renvoyant vers les journaux de l'hébergeur.

    Pourquoi pas Application Insights : l'application ne lui envoie rien
    aujourd'hui, et l'y brancher supposerait d'instrumenter le code puis de
    l'interroger avec des identifiants dédiés. La base est déjà là, disponible
    partout de la même façon, et suffit à répondre à « qu'est-ce qui casse en ce
    moment ».

    La table est bornée par `purge_error_logs`, sinon elle grossit sans fin.
    """

    level = models.CharField("Niveau", max_length=20, db_index=True)
    logger_name = models.CharField("Logger", max_length=120, blank=True)
    module = models.CharField("Module", max_length=120, blank=True)
    line_number = models.PositiveIntegerField("Ligne", null=True, blank=True)
    message = models.TextField("Message")
    traceback = models.TextField("Trace", blank=True)
    path = models.CharField("URL", max_length=255, blank=True)
    method = models.CharField("Méthode", max_length=10, blank=True)
    user_id_ref = models.PositiveIntegerField(
        "Utilisateur concerné",
        null=True,
        blank=True,
        help_text="Identifiant seul, sans clé étrangère : purger un compte ne doit pas effacer la trace de l'incident.",
    )
    # Empreinte du couple (module, ligne, type de message) : permet de regrouper
    # les répétitions d'une même erreur au lieu d'afficher mille fois la même.
    fingerprint = models.CharField("Empreinte", max_length=64, db_index=True, blank=True)
    occurrences = models.PositiveIntegerField("Occurrences", default=1)
    created_at = models.DateTimeField("Première occurrence", auto_now_add=True)
    last_seen_at = models.DateTimeField("Dernière occurrence", default=timezone.now)

    class Meta:
        verbose_name = "Erreur applicative"
        verbose_name_plural = "Erreurs applicatives"
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["-last_seen_at"], name="errorlog_seen_idx"),
            models.Index(fields=["fingerprint", "-last_seen_at"], name="errorlog_fp_idx"),
        ]

    def __str__(self):
        return f"{self.level} {self.module}:{self.line_number} – {self.message[:60]}"

    @property
    def is_recurring(self):
        return self.occurrences > 1
