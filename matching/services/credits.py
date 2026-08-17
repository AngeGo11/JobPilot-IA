"""
Compatibilité : anciennes fonctions de gestion des crédits.

La logique vit désormais dans `subscriptions.services.credits`, avec un
registre des mouvements. Ces deux fonctions conservent leur signature d'origine
pour que les appelants existants continuent de fonctionner, mais elles écrivent
au registre comme le reste.

Pour tout nouveau code, préférer `matching.use_cases.AIOperation`, qui garantit
le remboursement en cas d'échec au lieu de dépendre d'un `except` bien placé.
"""
import logging

from subscriptions.models import CreditEntry
from subscriptions.services.credits import InsufficientCredits, debit, refund

logger = logging.getLogger(__name__)


def consume_credit(user, operation="legacy"):
    """
    Consomme 1 crédit IA. Retourne True si l'opération peut se poursuivre.

    - Abonné premium : rien n'est débité, retourne True.
    - Crédits disponibles : décrément + écriture au registre, retourne True.
    - Solde vide : retourne False.
    """
    try:
        debit(user, operation=operation)
    except InsufficientCredits:
        return False
    return True


def refund_credit(user, note=""):
    """
    Rembourse la dernière consommation non encore annulée de l'utilisateur.

    L'ancienne version ajoutait aveuglément +1, ce qui pouvait créditer un
    utilisateur n'ayant jamais été débité (abonné premium, ou double appel dans
    deux blocs `except` imbriqués). On annule désormais une écriture précise,
    ce qui rend l'opération idempotente par construction.
    """
    if getattr(user, "is_premium", False):
        return

    last = (
        CreditEntry.objects.filter(
            user=user,
            reason=CreditEntry.Reason.CONSUMPTION,
            reversals__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if last is None:
        logger.warning(
            "Remboursement demandé pour user_id=%s sans consommation à annuler.",
            user.pk,
        )
        return
    refund(last, note=note)
