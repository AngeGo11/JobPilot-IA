"""
Transactions métier du domaine « matching ».

Ces objets contiennent l'enchaînement complet — vérifier, débiter, exécuter,
rembourser en cas d'échec — pour que les vues n'aient plus qu'à traduire le
résultat en HTTP.

Ce que ça remplace : dans `views.py`, la séquence « débiter puis appeler l'IA
puis rattraper six types d'exceptions puis rembourser » était recopiée quatre
fois. Chaque copie devait penser à rembourser dans chacune de ses branches
d'erreur — un oubli coûtait un crédit au client, silencieusement.
Ici, le remboursement est structurel : il vit dans le `except` de `run()` et
aucun chemin de sortie en erreur ne peut le contourner.
"""
import logging
import uuid

from django.conf import settings

from subscriptions.services.credits import InsufficientCredits, debit, refund
from utils.gemini_safe import FairUseExceeded, GeminiServiceUnavailable

logger = logging.getLogger(__name__)

__all__ = [
    "AIOperation",
    "AIOperationError",
    "InsufficientCredits",
    "MSG_NO_CREDIT",
    "MSG_FAIR_USE",
    "MSG_OVERLOADED",
]

# Messages destinés à l'utilisateur. Centralisés ici pour rester cohérents
# entre les vues HTML et les réponses JSON.
MSG_NO_CREDIT = (
    "Vous n'avez plus de crédits. Veuillez recharger votre compte pour "
    "utiliser l'analyse IA."
)
MSG_FAIR_USE = (
    "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte). "
    "Ne vous inquiétez pas, AUCUN crédit n'a été décompté."
)
MSG_OVERLOADED = (
    "Notre assistant IA est momentanément très sollicité. Ne vous inquiétez "
    "pas, AUCUN crédit n'a été décompté. Veuillez réessayer dans quelques instants."
)


class AIOperationError(Exception):
    """
    Échec d'une opération IA, déjà remboursée.

    Porte le message à afficher et le code HTTP attendu, pour que la vue n'ait
    aucune décision à reprendre.
    """

    def __init__(self, message, status=503, code="error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class AIOperation:
    """
    Exécute une opération facturée à l'unité.

        result = AIOperation("generate_letter").run(
            user, lambda: generator.generate_cover_letter(...)
        )

    Garanties :
      - un crédit est débité avant l'exécution, jamais après ;
      - toute exception rembourse ce crédit exactement une fois ;
      - les erreurs des services externes sont traduites en messages destinés
        à l'utilisateur, avec le bon code HTTP.
    """

    def __init__(self, operation, free=False):
        #: nom court de l'opération, tracé dans le registre des crédits
        self.operation = operation
        #: certaines actions (export PDF) n'appellent aucun modèle et ne se facturent pas
        self.free = free

    def run(self, user, action):
        """
        Exécute `action` immédiatement, dans la requête.

        Conservé pour les traitements courts et pour les tests. Les appels IA
        passent désormais par `enqueue()`.

        Lève `InsufficientCredits` si le solde est vide (aucun débit effectué),
        ou `AIOperationError` si l'exécution échoue (crédit déjà remboursé).
        """
        if self.free:
            return self._execute(user, action, entry=None)

        entry = debit(user, operation=self.operation)  # lève InsufficientCredits
        return self._execute(user, action, entry=entry)

    def enqueue(self, user, task, job_match=None, **kwargs):
        """
        Débite puis confie le travail à un worker. Retourne l'`AIJob` créé.

        Le débit reste synchrone volontairement : l'utilisateur doit apprendre
        tout de suite qu'il n'a plus de crédits, pas trente secondes plus tard
        par un statut d'échec. La tâche reçoit l'identifiant de l'écriture et se
        charge du remboursement si elle échoue.

        Lève `InsufficientCredits` si le solde est vide.
        """
        from matching.models import AIJob

        entry = None if self.free else debit(user, operation=self.operation)

        # L'identifiant est généré ici plutôt que par Celery : la ligne de suivi
        # doit exister **avant** que la tâche démarre. Sans cela, en mode
        # synchrone (tests, environnement sans broker) le worker chercherait un
        # `AIJob` que la requête n'a pas encore créé.
        task_id = str(uuid.uuid4())
        job = AIJob.objects.create(
            task_id=task_id,
            user=user,
            operation=self.operation,
            job_match=job_match,
            credit_entry=entry,
        )

        try:
            task.apply_async(kwargs=kwargs, task_id=task_id)
        except Exception:
            # Broker injoignable : rien n'a été exécuté, on rend le crédit.
            self._refund(entry, "File de tâches indisponible")
            job.delete()
            logger.exception("Impossible d'enfiler la tâche %s", self.operation)
            raise AIOperationError(MSG_OVERLOADED, status=503, code="queue_down")

        job.refresh_from_db()  # en mode synchrone, la tâche a déjà tout écrit
        return job

    # -- interne ------------------------------------------------------------

    def _execute(self, user, action, entry):
        try:
            return action()

        except (BrokenPipeError, ConnectionError):
            # Le navigateur a coupé pendant la génération : ce n'est pas une
            # faute de l'utilisateur, on lui rend son crédit.
            self._refund(entry, "Client déconnecté")
            logger.info(
                "Client déconnecté pendant %s (user_id=%s), crédit remboursé.",
                self.operation, user.pk,
            )
            raise AIOperationError(MSG_OVERLOADED, status=499, code="disconnected")

        except FairUseExceeded:
            self._refund(entry, "Quota horaire atteint")
            raise AIOperationError(MSG_FAIR_USE, status=429, code="fair_use")

        except GeminiServiceUnavailable:
            self._refund(entry, "Service IA indisponible")
            raise AIOperationError(MSG_OVERLOADED, status=503, code="unavailable")

        except ValueError as exc:
            self._refund(entry, "Données invalides")
            raise AIOperationError(
                f"Erreur de validation : {exc}. Aucun crédit n'a été décompté.",
                status=400,
                code="invalid",
            )

        except Exception as exc:
            self._refund(entry, f"Erreur inattendue : {type(exc).__name__}")
            logger.exception(
                "Échec de l'opération %s pour user_id=%s", self.operation, user.pk
            )
            # En développement, laisser remonter l'erreur d'origine : la masquer
            # derrière « serveurs surchargés » rend le débogage impossible.
            if settings.DEBUG:
                raise
            raise AIOperationError(MSG_OVERLOADED, status=503, code="error")

    def _refund(self, entry, note):
        """Le remboursement ne doit jamais masquer l'erreur métier d'origine."""
        try:
            refund(entry, note=note)
        except Exception:  # pragma: no cover - robustesse
            logger.exception(
                "Remboursement impossible pour l'écriture %s",
                getattr(entry, "pk", None),
            )
