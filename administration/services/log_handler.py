"""
Handler de journalisation écrivant les erreurs en base.

Trois pièges à éviter dans un handler qui écrit en base, tous traités ici :

1. **La récursion.** Si l'écriture échoue, le handler ne doit pas journaliser
   son propre échec — cela le rappellerait, en boucle. Un drapeau par thread
   coupe la réentrance.
2. **Les erreurs de base de données.** Journaliser une panne PostgreSQL dans
   PostgreSQL ne peut pas fonctionner. Ces enregistrements sont ignorés.
3. **Faire tomber la requête.** Un handler qui lève transforme un incident
   journalisé en incident visible par l'utilisateur. Tout est avalé.
"""
import hashlib
import logging
import re
import threading

_local = threading.local()

# Loggers ignorés : écrire en base une erreur venant de la base elle-même est
# soit impossible, soit le début d'une boucle.
LOGGERS_IGNORES = ("django.db", "django.db.backends", "administration.services.log_handler")

# Les identifiants numériques varient d'une occurrence à l'autre alors que
# l'erreur est la même ; on les neutralise pour le regroupement.
_CHIFFRES = re.compile(r"\d+")


class DatabaseErrorHandler(logging.Handler):
    """Enregistre chaque `logging.ERROR` dans `administration.ErrorLog`."""

    def emit(self, record):
        if getattr(_local, "en_cours", False):
            return
        if record.name.startswith(LOGGERS_IGNORES):
            return

        _local.en_cours = True
        try:
            self._enregistrer(record)
        except Exception:
            # Silence volontaire : voir le docstring du module. Le handler
            # console reste en place, l'information n'est donc pas perdue.
            pass
        finally:
            _local.en_cours = False

    # -- interne ------------------------------------------------------------

    def _enregistrer(self, record):
        from django.utils import timezone

        from administration.models import ErrorLog

        message = record.getMessage()[:4000]
        trace = self.format(record) if record.exc_info else ""
        empreinte = self._empreinte(record, message)

        requete = getattr(record, "request", None)
        chemin = getattr(requete, "path", "")[:255] if requete is not None else ""
        methode = getattr(requete, "method", "")[:10] if requete is not None else ""
        utilisateur = None
        if requete is not None:
            compte = getattr(requete, "user", None)
            if compte is not None and getattr(compte, "is_authenticated", False):
                utilisateur = compte.pk

        # Regroupement : une même erreur qui se répète incrémente un compteur
        # au lieu de remplir la table de lignes identiques.
        maintenant = timezone.now()
        misesajour = ErrorLog.objects.filter(fingerprint=empreinte).update(
            occurrences=models_F("occurrences") + 1,
            last_seen_at=maintenant,
        )
        if misesajour:
            return

        ErrorLog.objects.create(
            level=record.levelname[:20],
            logger_name=record.name[:120],
            module=record.module[:120],
            line_number=record.lineno,
            message=message,
            traceback=trace[:20000],
            path=chemin,
            method=methode,
            user_id_ref=utilisateur,
            fingerprint=empreinte,
            last_seen_at=maintenant,
        )

    @staticmethod
    def _empreinte(record, message):
        """Identifie une erreur indépendamment de ses valeurs variables."""
        base = f"{record.module}:{record.lineno}:{_CHIFFRES.sub('#', message)[:200]}"
        return hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()


def models_F(nom):
    """Import différé : ce module est chargé avant l'initialisation des apps."""
    from django.db.models import F

    return F(nom)
