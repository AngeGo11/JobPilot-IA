"""
Gestion des crédits IA : solde et registre.

Le solde rapide reste `CustomUser.ai_credits` (lu partout dans les gabarits et
les vues). Chaque mouvement écrit en plus une ligne dans `CreditEntry`, dans la
même transaction, pour qu'il existe toujours une trace de qui a débité quoi et
pourquoi.

Règle : personne ne modifie `ai_credits` directement en dehors de ce module.
"""
import logging

from django.db import transaction
from django.db.models import F, Sum

from subscriptions.models import CreditEntry

logger = logging.getLogger(__name__)


class InsufficientCredits(Exception):
    """L'utilisateur n'a ni abonnement actif ni crédit disponible."""


@transaction.atomic
def debit(user, operation="", note=""):
    """
    Consomme un crédit et enregistre le mouvement.

    Retourne l'écriture créée, ou `None` pour un abonné premium (rien n'est
    débité). Lève `InsufficientCredits` si le solde est vide.

    L'écriture et le décrément sont dans la même transaction : il devient
    impossible d'avoir un solde qui baisse sans ligne correspondante.
    """
    if getattr(user, "is_premium", False):
        return None

    # Décrément conditionnel : deux requêtes simultanées sur le dernier crédit
    # ne peuvent pas passer toutes les deux.
    updated = user.__class__.objects.filter(pk=user.pk, ai_credits__gt=0).update(
        ai_credits=F("ai_credits") - 1
    )
    if not updated:
        raise InsufficientCredits(
            "Solde de crédits insuffisant pour effectuer cette opération."
        )

    user.refresh_from_db(fields=["ai_credits"])
    entry = CreditEntry.objects.create(
        user=user,
        delta=-1,
        reason=CreditEntry.Reason.CONSUMPTION,
        operation=operation[:50],
        note=note[:255],
        balance_after=user.ai_credits,
    )
    logger.info(
        "Crédit débité : user_id=%s operation=%s solde=%s entry=%s",
        user.pk, operation, user.ai_credits, entry.pk,
    )
    return entry


@transaction.atomic
def refund(entry, note=""):
    """
    Annule une consommation précise.

    Prend l'écriture retournée par `debit()` plutôt qu'un utilisateur : on ne
    peut donc pas rembourser deux fois la même opération, ni rembourser un
    abonné premium qui n'a jamais été débité.
    """
    if entry is None:
        return None  # premium, ou débit jamais effectué

    if entry.reversals.exists():
        logger.warning(
            "Remboursement ignoré : l'écriture %s a déjà été annulée.", entry.pk
        )
        return None

    user = entry.user
    user.__class__.objects.filter(pk=user.pk).update(ai_credits=F("ai_credits") + 1)
    user.refresh_from_db(fields=["ai_credits"])

    reversal = CreditEntry.objects.create(
        user=user,
        delta=1,
        reason=CreditEntry.Reason.REFUND,
        operation=entry.operation,
        reverses=entry,
        note=note[:255] or "Échec de l'opération",
        balance_after=user.ai_credits,
    )
    logger.info(
        "Crédit remboursé : user_id=%s operation=%s solde=%s annule=%s",
        user.pk, entry.operation, user.ai_credits, entry.pk,
    )
    return reversal


@transaction.atomic
def grant(user, amount, reason, note=""):
    """
    Ajoute (ou retire) des crédits hors consommation : inscription, achat,
    geste commercial. `amount` négatif pour une correction à la baisse.
    """
    if amount == 0:
        return None

    user.__class__.objects.filter(pk=user.pk).update(ai_credits=F("ai_credits") + amount)
    user.refresh_from_db(fields=["ai_credits"])

    # Un solde négatif bloquerait `can_generate` durablement.
    if user.ai_credits < 0:
        correction = -user.ai_credits
        user.__class__.objects.filter(pk=user.pk).update(ai_credits=0)
        user.refresh_from_db(fields=["ai_credits"])
        amount += correction

    if amount == 0:
        return None

    return CreditEntry.objects.create(
        user=user,
        delta=amount,
        reason=reason,
        note=note[:255],
        balance_after=user.ai_credits,
    )


def ledger_balance(user):
    """Solde reconstitué depuis le registre — sert à détecter une dérive."""
    return CreditEntry.objects.filter(user=user).aggregate(total=Sum("delta"))["total"] or 0


def history(user, limit=50):
    return (
        CreditEntry.objects.filter(user=user)
        .select_related("reverses")
        .order_by("-created_at")[:limit]
    )
