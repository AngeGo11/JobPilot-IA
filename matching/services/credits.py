"""
Gestion de la consommation des crédits IA.
Utilisé pour les fonctionnalités du Groupe A (crédits OU abonnement).
"""
import logging
from django.db.models import F

logger = logging.getLogger(__name__)


def consume_credit(user):
    """
    Consomme 1 crédit IA pour l'utilisateur.
    - Si user.is_premium : ne déduit rien, retourne True.
    - Si user.ai_credits > 0 : décrémente de 1 (F() pour être thread-safe), sauvegarde, retourne True.
    - Sinon : retourne False.
    """
    if user.is_premium:
        return True
    # Mise à jour atomique pour éviter les race conditions
    updated = user.__class__.objects.filter(
        pk=user.pk,
        ai_credits__gt=0
    ).update(ai_credits=F('ai_credits') - 1)
    if updated:
        user.refresh_from_db()
        return True
    return False


def refund_credit(user):
    """
    Rembourse 1 crédit IA à l'utilisateur (ex. après échec de l'API ou annulation).
    - Si user.is_premium : ne fait rien, retourne.
    - Sinon : incrémente de 1 (F() pour être thread-safe), log.
    """
    if getattr(user, 'is_premium', False):
        return
    updated = user.__class__.objects.filter(pk=user.pk).update(
        ai_credits=F('ai_credits') + 1
    )
    if updated:
        user.refresh_from_db()
        logger.info(
            "Crédit remboursé à l'utilisateur user_id=%s suite à une erreur ou annulation (Safe Credit Deduction).",
            user.pk,
        )
