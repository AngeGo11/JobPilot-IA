"""Filtres d'affichage propres au back-office."""
from django import template

register = template.Library()

# Palette alignée sur celle du dashboard candidat (vert / ambre / rouge).
STATUS_STYLES = {
    "ok": "bg-emerald-100 text-emerald-800 border-emerald-200",
    "warn": "bg-amber-100 text-amber-800 border-amber-200",
    "error": "bg-red-100 text-red-800 border-red-200",
    "success": "bg-emerald-100 text-emerald-800 border-emerald-200",
    "running": "bg-blue-100 text-blue-800 border-blue-200",
    "pending": "bg-slate-100 text-slate-700 border-slate-200",
    "failure": "bg-red-100 text-red-800 border-red-200",
}

STATUS_DOTS = {
    "ok": "bg-emerald-500",
    "warn": "bg-amber-500",
    "error": "bg-red-500",
    "success": "bg-emerald-500",
    "running": "bg-blue-500",
    "pending": "bg-slate-400",
    "failure": "bg-red-500",
}

STATUS_LABELS = {
    "ok": "Opérationnel",
    "warn": "À surveiller",
    "error": "Incident",
}


@register.filter
def status_badge(status):
    """Classes Tailwind du badge correspondant à un statut de santé."""
    return STATUS_STYLES.get(status, "bg-slate-100 text-slate-700 border-slate-200")


@register.filter
def status_dot(status):
    return STATUS_DOTS.get(status, "bg-slate-400")


@register.filter
def status_label(status):
    return STATUS_LABELS.get(status, status)


@register.filter
def log_level_style(level):
    """Couleur d'une ligne de log selon sa gravité."""
    return {
        "CRITICAL": "text-red-700 bg-red-50",
        "ERROR": "text-red-700 bg-red-50",
        "WARNING": "text-amber-700 bg-amber-50",
        "INFO": "text-slate-600 bg-slate-50",
        "DEBUG": "text-slate-400 bg-slate-50",
    }.get(level, "text-slate-600 bg-slate-50")


@register.filter
def get_item(mapping, key):
    """Accès à une clé de dictionnaire depuis un template (`{{ d|get_item:k }}`)."""
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None


@register.filter
def duration(seconds):
    """Formate une durée en secondes de façon lisible."""
    if seconds is None:
        return "—"
    if seconds < 1:
        return "< 1 s"
    if seconds < 60:
        return f"{seconds:.0f} s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min {rest:02d} s"


@register.filter
def trend_style(delta):
    """Vert si en hausse, rouge si en baisse, neutre si inconnu."""
    if delta is None:
        return "text-slate-400"
    if delta > 0:
        return "text-emerald-600"
    if delta < 0:
        return "text-red-600"
    return "text-slate-500"


@register.filter
def trend_icon(delta):
    if delta is None:
        return "fa-minus"
    if delta > 0:
        return "fa-arrow-trend-up"
    if delta < 0:
        return "fa-arrow-trend-down"
    return "fa-minus"
