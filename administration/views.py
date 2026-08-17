"""
Back-office JobPilot-AI.

Toutes les vues sont réservées à `is_staff`. Les vues qui exposent ou modifient
des données personnelles écrivent dans le journal d'audit (`AdminAuditLog`).
"""
import csv
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from administration.decorators import staff_required, superuser_required
from administration.forms import (
    ExtendSubscriptionForm,
    GrantCreditsForm,
    SiteSettingsForm,
)
from administration.models import AdminAuditLog, SiteSettings, TaskRun
from administration.services import health, logs, metrics
from administration.services.audit import log_action
from matching.models import AIJob, JobAlert, JobMatch
from resumes.models import Resume
from subscriptions.models import CreditEntry, Transaction
from subscriptions.services.credits import grant, history, ledger_balance
from users.models import SubscriptionPlan

logger = logging.getLogger(__name__)
User = get_user_model()

PAGE_SIZE = 25


# --------------------------------------------------------------------------- #
# Vue d'ensemble
# --------------------------------------------------------------------------- #

@staff_required
def overview(request):
    """Tableau de bord principal : inscriptions, revenus, activité, santé."""
    series, peak = metrics.signups_series(days=30)
    checks, overall = health.run_all()

    return render(request, "administration/overview.html", {
        "section": "overview",
        "users": metrics.user_metrics(),
        "revenue": metrics.revenue_metrics(),
        "content": metrics.content_metrics(),
        "plans": metrics.plan_breakdown(),
        "funnel": metrics.activation_funnel(),
        "series": series,
        "series_peak": peak,
        "recent_signups": metrics.recent_signups(),
        "expiring": metrics.expiring_subscriptions(),
        "health_overall": overall,
        "health_issues": [c for c in checks if c["status"] != health.OK],
    })


# --------------------------------------------------------------------------- #
# Utilisateurs
# --------------------------------------------------------------------------- #

@staff_required
def user_list(request):
    """Liste des inscrits, avec recherche et filtres."""
    query = request.GET.get("q", "").strip()
    plan = request.GET.get("plan", "")
    status = request.GET.get("status", "")
    sort = request.GET.get("sort", "-date_joined")

    queryset = User.objects.annotate(
        resume_count=Count("resumes", distinct=True),
        match_count=Count("jobmatch", distinct=True),
        spent=Sum("stripe_transactions__amount"),
    )

    if query:
        queryset = queryset.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    if plan:
        queryset = queryset.filter(subscription_plan=plan)

    now = timezone.now()
    if status == "premium":
        queryset = queryset.filter(subscription_end_date__gt=now)
    elif status == "free":
        queryset = queryset.filter(
            Q(subscription_end_date__isnull=True) | Q(subscription_end_date__lte=now)
        )
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)
    elif status == "staff":
        queryset = queryset.filter(is_staff=True)

    allowed_sorts = {
        "-date_joined", "date_joined", "-last_login", "email",
        "-resume_count", "-match_count", "-spent",
    }
    queryset = queryset.order_by(sort if sort in allowed_sorts else "-date_joined")

    page_obj = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))

    # Conserve les filtres dans les liens de pagination.
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "administration/users.html", {
        "section": "users",
        "page_obj": page_obj,
        "query": query,
        "plan": plan,
        "status": status,
        "sort": sort,
        "plans": SubscriptionPlan.choices,
        "querystring": params.urlencode(),
        "totals": metrics.user_metrics(),
    })


@staff_required
def user_detail(request, user_id):
    """Fiche détaillée d'un inscrit. La consultation est journalisée (RGPD)."""
    target = get_object_or_404(
        User.objects.select_related("profile", "stripe_subscription"), pk=user_id
    )
    log_action(request, AdminAuditLog.Action.USER_VIEWED, f"utilisateur #{target.pk}")

    resumes = (
        Resume.objects.filter(user=target)
        .prefetch_related(Prefetch("job_alerts", queryset=JobAlert.objects.all()))
        .order_by("-uploaded_at")
    )
    match_stats = JobMatch.objects.filter(user=target).aggregate(
        total=Count("id"),
        unlocked=Count("id", filter=Q(is_unlocked=True)),
        applied=Count("id", filter=Q(status="applied")),
    )
    transactions = Transaction.objects.filter(user=target).order_by("-created_at")[:20]
    total_spent = Transaction.objects.filter(user=target).aggregate(
        total=Sum("amount")
    )["total"]

    return render(request, "administration/user_detail.html", {
        "section": "users",
        "target": target,
        "resumes": resumes,
        "match_stats": match_stats,
        "transactions": transactions,
        "total_spent": total_spent,
        "credit_history": history(target, limit=25),
        "ledger_balance": ledger_balance(target),
        "credits_form": GrantCreditsForm(),
        "extend_form": ExtendSubscriptionForm(),
        "audit_entries": AdminAuditLog.objects.filter(
            target=f"utilisateur #{target.pk}"
        ).select_related("actor")[:10],
    })


@staff_required
@require_POST
def user_action(request, user_id):
    """
    Actions d'assistance sur un compte : (dés)activation, crédits, prolongation.

    Chaque action est journalisée avec son motif. On refuse toute action d'un
    admin sur son propre compte ou sur un superutilisateur, pour éviter qu'une
    erreur de manipulation ne verrouille l'accès au back-office.
    """
    target = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action")

    if target.pk == request.user.pk:
        messages.error(request, "Vous ne pouvez pas appliquer cette action à votre propre compte.")
        return redirect("administration:user_detail", user_id=target.pk)
    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, "Seul un super-administrateur peut agir sur ce compte.")
        return redirect("administration:user_detail", user_id=target.pk)

    if action == "toggle_active":
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        log_action(
            request,
            AdminAuditLog.Action.USER_REACTIVATED if target.is_active
            else AdminAuditLog.Action.USER_DEACTIVATED,
            f"utilisateur #{target.pk}",
            email=target.email,
        )
        messages.success(
            request,
            f"Compte {'réactivé' if target.is_active else 'désactivé'} pour {target.email}.",
        )

    elif action == "grant_credits":
        form = GrantCreditsForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data["amount"]
            # Passe par le registre : un ajustement manuel est précisément le
            # genre de mouvement qu'il faut pouvoir justifier plus tard.
            # `grant` borne le solde à zéro (un solde négatif bloquerait
            # `can_generate` durablement).
            grant(
                target,
                amount,
                reason=CreditEntry.Reason.ADMIN_GRANT,
                note=f"{request.user.email} — {form.cleaned_data['reason']}",
            )
            log_action(
                request,
                AdminAuditLog.Action.CREDITS_GRANTED,
                f"utilisateur #{target.pk}",
                amount=amount,
                reason=form.cleaned_data["reason"],
                new_balance=target.ai_credits,
            )
            messages.success(
                request,
                f"Solde mis à jour : {target.ai_credits} crédit(s) pour {target.email}.",
            )
        else:
            messages.error(request, "Ajustement de crédits invalide : " + form.errors.as_text())

    elif action == "extend_subscription":
        form = ExtendSubscriptionForm(request.POST)
        if form.is_valid():
            days = form.cleaned_data["days"]
            now = timezone.now()
            # On repart de la date de fin si elle est encore dans le futur,
            # sinon de maintenant : prolonger un abonnement expiré depuis un mois
            # ne doit pas offrir un mois de rattrapage silencieux.
            base = target.subscription_end_date if target.is_premium else now
            target.subscription_end_date = base + timedelta(days=days)
            target.save(update_fields=["subscription_end_date"])
            log_action(
                request,
                AdminAuditLog.Action.SUBSCRIPTION_EXTENDED,
                f"utilisateur #{target.pk}",
                days=days,
                reason=form.cleaned_data["reason"],
                new_end_date=target.subscription_end_date.isoformat(),
            )
            messages.success(
                request,
                f"Abonnement prolongé jusqu'au "
                f"{timezone.localtime(target.subscription_end_date):%d/%m/%Y}.",
            )
        else:
            messages.error(request, "Prolongation invalide : " + form.errors.as_text())

    else:
        messages.error(request, "Action inconnue.")

    return redirect("administration:user_detail", user_id=target.pk)


@staff_required
def export_users(request):
    """
    Export CSV des inscrits, sans données personnelles directes.

    On exporte l'identifiant technique et des agrégats : un export nominatif
    n'a pas d'usage ici et multiplierait les copies de données personnelles.
    """
    log_action(request, AdminAuditLog.Action.EXPORT_RUN, "export utilisateurs (anonymisé)")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response["Content-Disposition"] = f'attachment; filename="jobpilot-inscrits-{stamp}.csv"'
    response.write("﻿")  # BOM : Excel ouvre le fichier en UTF-8

    writer = csv.writer(response, delimiter=";")
    writer.writerow([
        "id", "date_inscription", "derniere_connexion", "actif", "plan",
        "fin_abonnement", "credits", "nb_cv", "nb_matchs", "total_paye_eur",
    ])
    queryset = User.objects.annotate(
        resume_count=Count("resumes", distinct=True),
        match_count=Count("jobmatch", distinct=True),
        spent=Sum("stripe_transactions__amount"),
    ).order_by("date_joined").iterator(chunk_size=500)

    for user in queryset:
        writer.writerow([
            user.pk,
            timezone.localtime(user.date_joined).strftime("%Y-%m-%d"),
            timezone.localtime(user.last_login).strftime("%Y-%m-%d") if user.last_login else "",
            "oui" if user.is_active else "non",
            user.get_subscription_plan_display() or "",
            timezone.localtime(user.subscription_end_date).strftime("%Y-%m-%d")
            if user.subscription_end_date else "",
            user.ai_credits,
            user.resume_count,
            user.match_count,
            user.spent or 0,
        ])
    return response


# --------------------------------------------------------------------------- #
# Revenus
# --------------------------------------------------------------------------- #

@staff_required
def revenue(request):
    """Suivi financier : encaissements Stripe, MRR estimé, abonnés."""
    # La liste montre TOUT, y compris le mode test : masquer des lignes
    # existantes ferait douter de l'intégrité des données. Le mode est
    # signalé sur chaque ligne, et seuls les totaux excluent les tests.
    page_obj = Paginator(
        Transaction.objects.select_related("user").order_by("-created_at"), PAGE_SIZE
    ).get_page(request.GET.get("page"))

    return render(request, "administration/revenue.html", {
        "section": "revenue",
        "revenue": metrics.revenue_metrics(),
        "plans": metrics.plan_breakdown(),
        "users": metrics.user_metrics(),
        "page_obj": page_obj,
        "expiring": metrics.expiring_subscriptions(days=14, limit=20),
        "monthly": monthly_revenue(),
    })


def monthly_revenue(months=6):
    """Encaissements par mois, du plus ancien au plus récent. Hors mode test."""
    from django.db.models.functions import TruncMonth

    since = timezone.now() - timedelta(days=31 * months)
    rows = (
        Transaction.objects.filter(amount__isnull=False, created_at__gte=since)
        .exclude(stripe_session_id__startswith=Transaction.TEST_SESSION_PREFIX)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("month")
    )
    rows = list(rows)
    peak = max((row["total"] for row in rows), default=0) or 1
    for row in rows:
        row["height"] = round(row["total"] * 100 / peak)
    return rows


# --------------------------------------------------------------------------- #
# Contenu et matching
# --------------------------------------------------------------------------- #

@staff_required
def content(request):
    """Volumétrie métier : CV, offres France Travail, matchs, alertes."""
    now = timezone.now()
    alerts = (
        JobAlert.objects.select_related("resume", "resume__user")
        .order_by("is_active", "last_checked")
    )
    page_obj = Paginator(alerts, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(request, "administration/content.html", {
        "section": "content",
        "content": metrics.content_metrics(),
        "semantic": metrics.semantic_comparison(),
        "top_offers": metrics.top_offers(),
        "page_obj": page_obj,
        "stale_threshold": now - timedelta(days=2),
        "match_status": (
            JobMatch.objects.values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        ),
    })


# --------------------------------------------------------------------------- #
# Paramètres généraux
# --------------------------------------------------------------------------- #

@superuser_required
def site_settings(request):
    """
    Édition des paramètres généraux.

    Réservé aux super-administrateurs : ces réglages coupent le site ou
    modifient les quotas facturés.
    """
    instance = SiteSettings.load()

    if request.method == "POST":
        form = SiteSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            log_action(
                request,
                AdminAuditLog.Action.SETTINGS_UPDATED,
                "paramètres du site",
                changed=sorted(form.changed_data),
            )
            messages.success(request, "Paramètres enregistrés.")
            return redirect("administration:settings")
        messages.error(request, "Le formulaire contient des erreurs.")
    else:
        form = SiteSettingsForm(instance=instance)

    return render(request, "administration/settings.html", {
        "section": "settings",
        "form": form,
        "instance": instance,
        "environment": _environment_summary(),
    })


def _environment_summary():
    """
    État des variables d'environnement sensibles : « configuré » ou « manquant ».

    On n'affiche jamais les valeurs — une clé Stripe ou un mot de passe SMTP
    lisible dans une page web serait une fuite en cas de capture d'écran ou de
    session admin compromise.
    """
    from django.conf import settings as dj_settings

    keys = [
        ("SECRET_KEY", "Clé secrète Django"),
        ("STRIPE_SECRET_KEY", "Stripe – clé secrète"),
        ("STRIPE_WEBHOOK_SECRET", "Stripe – secret webhook"),
        ("STRIPE_PRICE_PASS24H", "Stripe – tarif Pass 24h"),
        ("STRIPE_PRICE_SPRINT", "Stripe – tarif Sprint"),
        ("STRIPE_PRICE_PRO", "Stripe – tarif Pro"),
        ("STRIPE_PRICE_PACK", "Stripe – tarif Pack crédits"),
        ("CLIENT_ID", "France Travail – identifiant"),
        ("CLIENT_SECRET_KEY", "France Travail – secret"),
        ("EMAIL_HOST", "SMTP – hôte"),
        ("EMAIL_HOST_USER", "SMTP – utilisateur"),
        ("EMAIL_HOST_PASSWORD", "SMTP – mot de passe"),
    ]
    return [
        {"label": label, "configured": bool(getattr(dj_settings, name, None)), "name": name}
        for name, label in keys
    ]


# --------------------------------------------------------------------------- #
# Supervision
# --------------------------------------------------------------------------- #

@staff_required
def supervision(request):
    """Santé des dépendances, tâches planifiées et erreurs récentes."""
    checks, overall = health.run_all()
    entries, log_note = logs.tail_entries("error_file", limit=40)
    hot_modules, error_count, _ = logs.error_summary()

    runs = TaskRun.objects.all()[:30]
    last_by_task = {}
    for name in health.EXPECTED_TASKS:
        last_by_task[name] = (
            TaskRun.objects.filter(name=name).order_by("-started_at").first()
        )

    # Traitements IA : ce que la file de tâches est en train de faire.
    ai_since = timezone.now() - timedelta(hours=24)
    ai_stats = AIJob.objects.filter(created_at__gte=ai_since).aggregate(
        total=Count("id"),
        running=Count("id", filter=Q(status__in=["pending", "running"])),
        success=Count("id", filter=Q(status="success")),
        failure=Count("id", filter=Q(status="failure")),
    )
    ai_recent = AIJob.objects.select_related("user").order_by("-created_at")[:10]
    # Une tâche « en cours » depuis plus d'un quart d'heure signale un worker
    # tombé en cours de route : le travail ne reprendra pas tout seul.
    ai_stuck = AIJob.objects.filter(
        status__in=["pending", "running"],
        created_at__lt=timezone.now() - timedelta(minutes=15),
    ).count()

    return render(request, "administration/supervision.html", {
        "section": "supervision",
        "ai_stats": ai_stats,
        "ai_recent": ai_recent,
        "ai_stuck": ai_stuck,
        "checks": checks,
        "overall": overall,
        "runs": runs,
        "last_by_task": last_by_task,
        "expected_tasks": health.EXPECTED_TASKS,
        "log_entries": entries,
        "log_note": log_note,
        "hot_modules": hot_modules,
        "error_count": error_count,
        "content": metrics.content_metrics(),
    })


@staff_required
def health_json(request):
    """Point d'entrée JSON pour le rafraîchissement automatique de la supervision."""
    checks, overall = health.run_all()
    return JsonResponse({
        "overall": overall,
        "checks": checks,
        "checked_at": timezone.localtime().strftime("%d/%m/%Y %H:%M:%S"),
    })


# --------------------------------------------------------------------------- #
# Journal d'audit
# --------------------------------------------------------------------------- #

@staff_required
def audit(request):
    """Historique des actions réalisées depuis le back-office."""
    queryset = AdminAuditLog.objects.select_related("actor")
    action = request.GET.get("action", "")
    if action:
        queryset = queryset.filter(action=action)

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "administration/audit.html", {
        "section": "audit",
        "page_obj": Paginator(queryset, 50).get_page(request.GET.get("page")),
        "actions": AdminAuditLog.Action.choices,
        "action": action,
        "querystring": params.urlencode(),
    })
