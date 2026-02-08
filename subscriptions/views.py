from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.http import HttpResponse
from dotenv import load_dotenv

from .services.stripe_api import create_checkout_session, get_stripe, handle_checkout_completed, handle_subscription_updated

load_dotenv()

def pricing_view(request):
    """Page de tarification avec les formules."""
    context = {
        'stripe_publishable_key': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '',
    }
    return render(request, 'subscriptions/pricing.html', context)


@login_required
@require_POST
def create_checkout(request):
    """
    Crée une session Stripe Checkout pour le plan envoyé en POST (plan=pass24h|sprint|pro|pack).
    Redirige vers Stripe ou vers la page tarifs en cas d'erreur.
    """
    plan = request.POST.get('plan', '').strip().lower()
    if plan not in ('pass24h', 'sprint', 'pro', 'pack'):
        return redirect('pricing')
    if not getattr(settings, 'STRIPE_SECRET_KEY', None):
        return redirect('pricing')
    url = create_checkout_session(request, plan)
    if url:
        return redirect(url)
    return redirect('pricing')


@login_required
@require_GET
def success_view(request):
    """Page de succès après paiement (retour depuis Stripe)."""
    session_id = request.GET.get('session_id')
    return render(request, 'subscriptions/success.html', {'session_id': session_id})


@require_GET
def cancel_view(request):
    """Annulation : retour à la page tarifs."""
    return redirect('pricing')


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """
    Webhook Stripe : vérifie la signature et traite les événements.
    Événements gérés : checkout.session.completed, customer.subscription.updated.
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
    if not webhook_secret:
        return HttpResponse('Webhook non configuré', status=500)
    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError as e:
        return HttpResponse(f'Payload invalide: {e}', status=400)
    except Exception as e:
        return HttpResponse(f'Signature invalide: {e}', status=400)

    if event['type'] == 'checkout.session.completed':
        handle_checkout_completed(event['data']['object'])
    elif event['type'] == 'customer.subscription.updated':
        handle_subscription_updated(event['data']['object'])
    elif event['type'] == 'customer.subscription.deleted':
        from .services.stripe_api import handle_subscription_deleted
        handle_subscription_deleted(event['data']['object'])

    return HttpResponse(status=200)
