"""
Agrégations pour le back-office.

Tout est calculé en SQL (aggregate/annotate) plutôt qu'en Python : ces vues
doivent rester rapides même avec plusieurs dizaines de milliers de lignes.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from matching.models import JobAlert, JobMatch, JobOffer
from resumes.models import Resume
from subscriptions.models import Transaction
from users.models import SubscriptionPlan

User = get_user_model()

# Tarifs publics, utilisés pour estimer le revenu récurrent mensuel par plan.
# Source : STRIPE_PRICE_* dans settings.py (2,99 € pass 24h, 5,99 €/sem, 14,99 €/mois).
MRR_BY_PLAN = {
    SubscriptionPlan.PASS24H: Decimal("0"),      # paiement unique, hors récurrent
    SubscriptionPlan.SPRINT: Decimal("25.96"),   # 5,99 €/semaine ≈ 4,33 semaines
    SubscriptionPlan.PRO: Decimal("14.99"),
}


def _pct(part, whole):
    """Pourcentage arrondi à 0,1 près, 0 si le dénominateur est nul."""
    if not whole:
        return 0.0
    return round(part * 100 / whole, 1)


def _delta_pct(current, previous):
    """
    Évolution en % entre deux périodes. Retourne None quand la période
    précédente est vide (afficher « +∞ % » n'aurait pas de sens).
    """
    if not previous:
        return None
    return round((current - previous) * 100 / previous, 1)


def user_metrics():
    """Compteurs d'inscriptions et d'activité utilisateurs."""
    now = timezone.now()
    d1, d7, d30, d60 = (now - timedelta(days=n) for n in (1, 7, 30, 60))

    counts = User.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        inactive=Count("id", filter=Q(is_active=False)),
        staff=Count("id", filter=Q(is_staff=True)),
        new_24h=Count("id", filter=Q(date_joined__gte=d1)),
        new_7d=Count("id", filter=Q(date_joined__gte=d7)),
        new_30d=Count("id", filter=Q(date_joined__gte=d30)),
        prev_30d=Count("id", filter=Q(date_joined__gte=d60, date_joined__lt=d30)),
        premium=Count("id", filter=Q(subscription_end_date__gt=now)),
        expired=Count("id", filter=Q(subscription_end_date__lte=now)),
        never_logged_in=Count("id", filter=Q(last_login__isnull=True)),
        active_7d=Count("id", filter=Q(last_login__gte=d7)),
        credits_total=Coalesce(Sum("ai_credits"), 0),
    )

    counts["premium_rate"] = _pct(counts["premium"], counts["total"])
    counts["growth_30d"] = _delta_pct(counts["new_30d"], counts["prev_30d"])
    counts["active_rate_7d"] = _pct(counts["active_7d"], counts["total"])
    return counts


def plan_breakdown():
    """Répartition des abonnés actifs par formule, avec MRR estimé."""
    now = timezone.now()
    rows = (
        User.objects.filter(subscription_end_date__gt=now)
        .values("subscription_plan")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    labels = dict(SubscriptionPlan.choices)
    result = []
    for row in rows:
        plan = row["subscription_plan"]
        result.append({
            "plan": plan,
            "label": labels.get(plan, "Non renseigné"),
            "count": row["count"],
            "mrr": MRR_BY_PLAN.get(plan, Decimal("0")) * row["count"],
        })
    return result


def signups_series(days=30):
    """
    Inscriptions par jour sur `days` jours, trous comblés à zéro.

    Retourne une liste de dicts prête à l'affichage : {date, label, count, height}
    où `height` est le pourcentage de la valeur max (pour la hauteur des barres).
    """
    since = timezone.now() - timedelta(days=days - 1)
    rows = (
        User.objects.filter(date_joined__gte=since)
        .annotate(day=TruncDate("date_joined"))
        .values("day")
        .annotate(count=Count("id"))
    )
    by_day = {row["day"]: row["count"] for row in rows}

    today = timezone.localdate()
    series = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        series.append({"date": day, "count": by_day.get(day, 0)})

    peak = max((point["count"] for point in series), default=0)
    for point in series:
        # 4 % minimum pour qu'un jour à zéro reste visible comme un socle.
        point["height"] = round(point["count"] * 100 / peak) if peak else 0
        point["label"] = point["date"].strftime("%d/%m")
    return series, peak


def revenue_metrics():
    """
    Chiffre d'affaires réellement encaissé.

    Deux filtres, pour deux raisons distinctes :

    - `amount__isnull=False` : les entrées créées avant l'ajout du champ
      `amount` sont à NULL et fausseraient une moyenne si on les comptait
      comme des paiements à 0 €.
    - exclusion du mode test : les paiements de mise au point (`cs_test_…`)
      partagent la table avec les vrais. Les additionner gonfle le chiffre
      d'affaires — d'un facteur trois sur les premières semaines d'un produit,
      ce qui rend l'indicateur trompeur au moment où il compte le plus.

    Le volume de test est retourné à part, sous `test_*`, plutôt que caché :
    voir qu'il existe évite de croire à une perte de données.
    """
    now = timezone.now()
    d7, d30, d60 = (now - timedelta(days=n) for n in (7, 30, 60))
    money = DecimalField(max_digits=12, decimal_places=2)
    zero = Value(Decimal("0.00"), output_field=money)

    est_test = Q(stripe_session_id__startswith=Transaction.TEST_SESSION_PREFIX)
    paid = Transaction.objects.filter(amount__isnull=False).exclude(est_test)
    stats = paid.aggregate(
        total=Coalesce(Sum("amount"), zero),
        total_7d=Coalesce(Sum("amount", filter=Q(created_at__gte=d7)), zero),
        total_30d=Coalesce(Sum("amount", filter=Q(created_at__gte=d30)), zero),
        prev_30d=Coalesce(
            Sum("amount", filter=Q(created_at__gte=d60, created_at__lt=d30)), zero
        ),
        avg_basket=Coalesce(Avg("amount"), zero),
        count=Count("id"),
        payers=Count("user", distinct=True),
    )
    stats["untracked_count"] = Transaction.objects.filter(amount__isnull=True).count()

    # Volume écarté, affiché séparément.
    test = Transaction.objects.filter(est_test).aggregate(
        count=Count("id"),
        total=Coalesce(Sum("amount"), zero),
    )
    stats["test_count"] = test["count"]
    stats["test_total"] = test["total"]

    stats["growth_30d"] = _delta_pct(stats["total_30d"], stats["prev_30d"])
    stats["mrr"] = sum((row["mrr"] for row in plan_breakdown()), Decimal("0"))
    stats["arpu"] = (
        (stats["total"] / stats["payers"]).quantize(Decimal("0.01"))
        if stats["payers"] else Decimal("0.00")
    )
    return stats


def content_metrics():
    """Volumétrie métier : CV, offres, matchs, alertes."""
    now = timezone.now()
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    resumes = Resume.objects.aggregate(
        total=Count("id"),
        new_7d=Count("id", filter=Q(uploaded_at__gte=d7)),
        analysed=Count("id", filter=~Q(detected_job_title=None) & ~Q(detected_job_title="")),
        with_owner=Count("user", distinct=True),
    )
    resumes["analysed_rate"] = _pct(resumes["analysed"], resumes["total"])

    offers = JobOffer.objects.aggregate(
        total=Count("id"),
        new_7d=Count("id", filter=Q(created_at__gte=d7)),
        new_30d=Count("id", filter=Q(created_at__gte=d30)),
    )

    matches = JobMatch.objects.aggregate(
        total=Count("id"),
        unlocked=Count("id", filter=Q(is_unlocked=True)),
        new_7d=Count("id", filter=Q(matched_at__gte=d7)),
        applied=Count("id", filter=Q(status="applied")),
        rejected=Count("id", filter=Q(status="rejected")),
        avg_score=Coalesce(Avg("score"), 0.0),
    )
    matches["unlock_rate"] = _pct(matches["unlocked"], matches["total"])
    matches["apply_rate"] = _pct(matches["applied"], matches["unlocked"])
    matches["avg_score"] = round(matches["avg_score"], 1)

    alerts = JobAlert.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        never_checked=Count("id", filter=Q(is_active=True, last_checked__isnull=True)),
        stale=Count(
            "id",
            filter=Q(is_active=True, last_checked__lt=now - timedelta(days=2)),
        ),
    )

    return {"resumes": resumes, "offers": offers, "matches": matches, "alerts": alerts}


def activation_funnel():
    """
    Entonnoir d'activation : inscrit → CV déposé → match débloqué → payé.

    C'est la métrique qui dit où les utilisateurs décrochent ; les compteurs
    bruts d'inscriptions ne le montrent pas.
    """
    total = User.objects.count()
    steps = [
        ("Inscrits", total),
        ("Ont déposé un CV", User.objects.filter(resumes__isnull=False).distinct().count()),
        (
            "Ont débloqué une offre",
            User.objects.filter(jobmatch__is_unlocked=True).distinct().count(),
        ),
        (
            "Ont payé",
            User.objects.filter(stripe_transactions__isnull=False).distinct().count(),
        ),
    ]
    return [
        {"label": label, "count": count, "rate": _pct(count, total)}
        for label, count in steps
    ]


def top_offers(limit=10):
    """Offres qui génèrent le plus de matchs débloqués — proxy de ce qui intéresse."""
    return (
        JobOffer.objects.annotate(
            match_count=Count("jobmatch"),
            unlocked_count=Count("jobmatch", filter=Q(jobmatch__is_unlocked=True)),
        )
        .filter(match_count__gt=0)
        .order_by("-unlocked_count", "-match_count")[:limit]
    )


def recent_signups(limit=8):
    return User.objects.order_by("-date_joined")[:limit]


def expiring_subscriptions(days=7, limit=10):
    """Abonnements qui arrivent à échéance — cible naturelle d'une relance."""
    now = timezone.now()
    return (
        User.objects.filter(
            subscription_end_date__gt=now,
            subscription_end_date__lte=now + timedelta(days=days),
        )
        .order_by("subscription_end_date")[:limit]
    )


def semantic_comparison():
    """
    Compare les deux méthodes de scoring sur les correspondances vectorisées.

    C'est la donnée qui permet de décider la bascule : tant que le mode ombre
    tourne, on regarde ici si le score sémantique change réellement le
    classement, et dans quel sens.
    """
    from administration.models import SiteSettings

    scored = JobMatch.objects.exclude(semantic_score__isnull=True)
    total_matches = JobMatch.objects.count()

    stats = scored.aggregate(
        compared=Count("id"),
        avg_keyword=Coalesce(Avg("score"), 0.0),
        avg_semantic=Coalesce(Avg("semantic_score"), 0.0),
        # Offres que le score par mots-clés retiendrait (>= 70) mais que le
        # sémantique écarte : c'est le bruit envoyé par email aujourd'hui.
        faux_positifs=Count("id", filter=Q(score__gte=70, semantic_score__lt=50)),
        # L'inverse : offres pertinentes que les mots-clés ratent.
        rattrapees=Count("id", filter=Q(score__lt=70, semantic_score__gte=70)),
        accord=Count("id", filter=Q(score__gte=70, semantic_score__gte=70)),
    )

    coverage = {
        "offers_total": JobOffer.objects.count(),
        "offers_embedded": JobOffer.objects.exclude(embedding__isnull=True).count(),
        "resumes_total": Resume.objects.count(),
        "resumes_embedded": Resume.objects.exclude(embedding__isnull=True).count(),
        "matches_total": total_matches,
    }
    coverage["offers_rate"] = _pct(coverage["offers_embedded"], coverage["offers_total"])
    coverage["resumes_rate"] = _pct(coverage["resumes_embedded"], coverage["resumes_total"])
    coverage["matches_rate"] = _pct(stats["compared"], total_matches)

    stats["avg_keyword"] = round(stats["avg_keyword"], 1)
    stats["avg_semantic"] = round(stats["avg_semantic"], 1)
    stats["enabled"] = SiteSettings.load().semantic_matching_enabled

    # Échantillon des plus gros désaccords : c'est là qu'on juge à l'œil si le
    # sémantique a raison. Un chiffre agrégé ne dit pas s'il se trompe.
    divergent = list(
        scored.select_related("job_offer", "resume")
        .filter(score__gte=70, semantic_score__lt=50)
        .order_by("semantic_score")[:8]
    )

    return {"stats": stats, "coverage": coverage, "divergent": divergent}
