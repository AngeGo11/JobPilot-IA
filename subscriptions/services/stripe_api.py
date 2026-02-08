"""
Service Stripe pour JobPilot : création de sessions Checkout et traitement des webhooks.
"""
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Plans reconnus (slug -> config)
PLANS = {
    'pass24h': {'price_id_setting': 'STRIPE_PRICE_PASS24H', 'mode': 'payment', 'duration_days': 1},
    'sprint': {'price_id_setting': 'STRIPE_PRICE_SPRINT', 'mode': 'subscription', 'duration_days': 7},
    'pro': {'price_id_setting': 'STRIPE_PRICE_PRO', 'mode': 'subscription', 'duration_days': 30},
    'pack': {'price_id_setting': 'STRIPE_PRICE_PACK', 'mode': 'payment', 'credits': 10},
}


def get_stripe():
    """Retourne le module stripe configuré avec la clé secrète."""
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_checkout_session(request, plan_slug):
    """
    Crée une session Stripe Checkout pour le plan donné.
    Retourne l'URL de redirection vers Stripe ou None en cas d'erreur.
    """
    if not settings.STRIPE_SECRET_KEY:
        logger.error("STRIPE_SECRET_KEY non configurée")
        return None
    plan_config = PLANS.get(plan_slug)
    if not plan_config:
        logger.warning(f"Plan inconnu: {plan_slug}")
        return None
    price_id = getattr(settings, plan_config['price_id_setting'], None)
    if not price_id:
        logger.warning(f"Price ID manquant pour le plan: {plan_slug}")
        return None

    stripe = get_stripe()
    user = request.user
    base_url = request.build_absolute_uri('/').rstrip('/')
    success_url = f"{base_url}/subscriptions/success/?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base_url}/subscriptions/pricing/"

    try:
        session = stripe.checkout.Session.create(
            mode=plan_config['mode'],
            line_items=[{'price': price_id, 'quantity': 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(user.id),
            metadata={'plan': plan_slug},
            customer_email=user.email if user.is_authenticated else None,
        )
        return session.url
    except Exception as e:
        logger.exception("Erreur création session Stripe: %s", e)
        return None


def apply_plan_to_user(user_id, plan_slug):
    """
    Applique les effets du plan à l'utilisateur (après paiement réussi).
    - pass24h / sprint / pro : met à jour subscription_end_date
    - pack : ajoute des crédits
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.warning("Utilisateur introuvable pour checkout: user_id=%s", user_id)
        return
    plan_config = PLANS.get(plan_slug)
    if not plan_config:
        return
    now = timezone.now()
    if 'duration_days' in plan_config:
        user.subscription_end_date = now + timedelta(days=plan_config['duration_days'])
        user.subscription_plan = plan_slug
        user.save(update_fields=['subscription_end_date', 'subscription_plan'])
        logger.info("Abonnement mis à jour: user_id=%s plan=%s jusqu'à %s", user_id, plan_slug, user.subscription_end_date)
    if plan_config.get('credits'):
        user.ai_credits = (user.ai_credits or 0) + plan_config['credits']
        user.save(update_fields=['ai_credits'])
        logger.info("Crédits ajoutés: user_id=%s +%s (total=%s)", user_id, plan_config['credits'], user.ai_credits)


def handle_checkout_completed(session):
    """
    Appelé par le webhook quand checkout.session.completed.
    session est l'objet Stripe (dict ou StripeObject).
    """
    client_reference_id = session.get('client_reference_id')
    plan = (session.get('metadata') or {}).get('plan')
    if not client_reference_id or not plan:
        logger.warning("checkout.session.completed sans client_reference_id ou metadata.plan")
        return
    mode = session.get('mode', 'payment')
    if mode == 'subscription':
        subscription_id = session.get('subscription')
        if subscription_id:
            _link_subscription_and_set_end_date(client_reference_id, subscription_id, plan)
        else:
            apply_plan_to_user(client_reference_id, plan)
    else:
        apply_plan_to_user(client_reference_id, plan)


def _link_subscription_and_set_end_date(user_id, stripe_subscription_id, plan_slug):
    """Récupère la période courante Stripe et met à jour l'utilisateur (date + type d'abonnement)."""
    from django.contrib.auth import get_user_model
    from subscriptions.models import StripeSubscription

    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return
    stripe = get_stripe()
    try:
        sub = stripe.Subscription.retrieve(stripe_subscription_id)
    except Exception as e:
        logger.exception("Erreur récupération abonnement Stripe: %s", e)
        return
    # Stripe renvoie un objet (attributs) : current_period_end est un timestamp Unix
    period_end = getattr(sub, 'current_period_end', None)
    update_fields = ['subscription_plan']
    if period_end:
        user.subscription_end_date = timezone.datetime.fromtimestamp(period_end, tz=timezone.get_current_timezone())
        update_fields.append('subscription_end_date')
    user.subscription_plan = plan_slug if plan_slug in ('pass24h', 'sprint', 'pro') else user.subscription_plan
    user.save(update_fields=update_fields)
    StripeSubscription.objects.update_or_create(
        user=user,
        defaults={'stripe_subscription_id': stripe_subscription_id}
    )
    logger.info("Abonnement lié: user_id=%s subscription_id=%s plan=%s jusqu'à %s", user_id, stripe_subscription_id, plan_slug, user.subscription_end_date)


def handle_subscription_updated(subscription):
    """
    Appelé par le webhook customer.subscription.updated (renouvellement).
    Met à jour subscription_end_date selon current_period_end.
    """
    from subscriptions.models import StripeSubscription

    sub_id = subscription.get('id') if hasattr(subscription, 'get') else getattr(subscription, 'id', None)
    period_end = subscription.get('current_period_end') if hasattr(subscription, 'get') else getattr(subscription, 'current_period_end', None)
    if not period_end:
        return
    try:
        stripe_sub = StripeSubscription.objects.get(stripe_subscription_id=sub_id)
    except StripeSubscription.DoesNotExist:
        logger.debug("Subscription updated inconnue: %s", sub_id)
        return
    stripe_sub.user.subscription_end_date = timezone.datetime.fromtimestamp(period_end, tz=timezone.get_current_timezone())
    stripe_sub.user.save(update_fields=['subscription_end_date'])
    logger.info("Abonnement renouvelé: user_id=%s jusqu'à %s", stripe_sub.user_id, stripe_sub.user.subscription_end_date)


def handle_subscription_deleted(subscription):
    """Appelé quand un abonnement est annulé : désactive le premium pour l'utilisateur."""
    from subscriptions.models import StripeSubscription

    sub_id = subscription.get('id')
    try:
        stripe_sub = StripeSubscription.objects.get(stripe_subscription_id=sub_id)
    except StripeSubscription.DoesNotExist:
        return
    user_id = stripe_sub.user_id
    stripe_sub.user.subscription_end_date = timezone.now()
    stripe_sub.user.subscription_plan = None
    stripe_sub.user.save(update_fields=['subscription_end_date', 'subscription_plan'])
    stripe_sub.delete()
    logger.info("Abonnement annulé: user_id=%s", user_id)
