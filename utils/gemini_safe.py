"""
Rate limiting et appels robustes à l'API Gemini.
- Limite globale RPM (anti-crash Free Tier).
- Limite par utilisateur/heure (Fair Use).
- Retry avec backoff exponentiel sur 429.
"""
import time
import logging
from typing import Optional, Any, Callable

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# --- Exceptions personnalisées ---

class GeminiServiceUnavailable(Exception):
    """Levée quand l'API Gemini reste indisponible après les réessais (ex. 429)."""
    pass


class FairUseExceeded(Exception):
    """Levée quand l'utilisateur a dépassé sa limite horaire d'appels Gemini."""
    pass


class GeminiConfigurationError(Exception):
    """
    Erreur permanente côté configuration : modèle inconnu, requête invalide,
    clé refusée. Réessayer n'y changera rien, et la présenter comme une
    « surcharge momentanée » envoie le diagnostic dans la mauvaise direction.
    """
    pass


# --- Rate limiting (cache Django) ---

def _rpm_cache_key() -> str:
    """Clé cache pour le compteur RPM global (fenêtre 1 minute)."""
    minute_window = int(time.time() // 60)
    return f"global_gemini_rpm:{minute_window}"


def _user_hourly_cache_key(user_id: int) -> str:
    """Clé cache pour le compteur horaire par utilisateur."""
    hour_window = int(time.time() // 3600)
    return f"user_{user_id}_hourly_usage:{hour_window}"


def _cache_incr(key: str, timeout: int) -> int:
    """
    Incrémente un compteur en cache de façon atomique si le backend le supporte (incr),
    sinon get/set (léger risque de double compte en forte concurrence).
    Retourne la nouvelle valeur.
    """
    try:
        cache.incr(key)
        return cache.get(key, 0)
    except (ValueError, TypeError):
        # Clé absente ou backend sans incr (ex. LocMem au premier appel)
        cache.set(key, 1, timeout=timeout)
        return 1


def ensure_gemini_rate_limit(user_id: Optional[int] = None) -> None:
    """
    Vérifie les deux limites avant un appel Gemini.
    - RPM global : si dépassé, attend 1 à 2 s puis réessaye (boucle courte).
    - Fair Use user : si dépassé, lève FairUseExceeded.
    En production multi-workers, utiliser un cache partagé (Redis) dans CACHES
    pour que les limites soient bien globales.
    """
    max_rpm = getattr(settings, 'GEMINI_MAX_RPM', 10)
    fair_use_limit = getattr(settings, 'GEMINI_FAIR_USE_LIMIT', 50)

    # Check 2 : Fair Use utilisateur (avant d'incrémenter quoi que ce soit)
    if user_id is not None:
        key_user = _user_hourly_cache_key(user_id)
        count = cache.get(key_user, 0)
        if count >= fair_use_limit:
            raise FairUseExceeded(
                "L'IA chauffe ! Pause café obligatoire (limite de sécurité atteinte)."
            )

    # Check 1 : RPM global (attendre puis réessayer jusqu'à 3 fois)
    for attempt in range(3):
        key_global = _rpm_cache_key()
        current = cache.get(key_global, 0)
        if current < max_rpm:
            break
        wait = 1 if attempt == 0 else 2
        logger.debug("Gemini RPM limit: waiting %ss (attempt %s)", wait, attempt + 1)
        time.sleep(wait)
    else:
        # Après 3 tentatives, on laisse passer pour ne pas bloquer indéfiniment
        pass

    # Incrémenter les compteurs (après la vérification)
    key_global = _rpm_cache_key()
    _cache_incr(key_global, timeout=120)

    if user_id is not None:
        key_user = _user_hourly_cache_key(user_id)
        _cache_incr(key_user, timeout=7200)


def _is_permanent_error(exc: BaseException) -> bool:
    """
    Détecte une erreur qui ne se résoudra pas d'elle-même : 400, 401, 403, 404.

    Sans cette distinction, un nom de modèle erroné consommait trois tentatives
    avec backoff avant d'être signalé comme une surcharge des serveurs.
    """
    msg = str(exc).lower()
    return any(code in msg for code in ("404", "not_found", "400", "invalid_argument",
                                        "401", "unauthenticated", "403", "permission_denied"))


def _is_429_or_resource_exhausted(exc: BaseException) -> bool:
    """Détecte erreur 429 / ResourceExhausted de l'API Gemini."""
    msg = str(exc).lower()
    if "429" in msg or "resource exhausted" in msg or "quota" in msg:
        return True
    # google.generativeai peut lever des exceptions avec ces messages
    if hasattr(exc, "message"):
        return "429" in str(getattr(exc, "message", "")) or "resource exhausted" in str(getattr(exc, "message", "")).lower()
    return False


def call_gemini_with_retry(
    generate_fn: Callable[[], Any],
    max_retries: int = 3,
) -> Any:
    """
    Exécute l'appel à generate_content (via un callable sans arguments).
    Backoff exponentiel 1s, 2s, 4s sur 429 / ResourceExhausted.
    Lève GeminiServiceUnavailable après échec final.
    """
    delays = [1, 2, 4]
    last_exc = None
    for attempt in range(max_retries):
        try:
            return generate_fn()
        except Exception as e:
            last_exc = e
            if _is_permanent_error(e):
                logger.error("Erreur Gemini permanente, pas de réessai : %s", e)
                raise GeminiConfigurationError(str(e)) from e
            if _is_429_or_resource_exhausted(e) and attempt < max_retries - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning("Gemini 429/ResourceExhausted, retry in %ss (attempt %s/%s)", delay, attempt + 1, max_retries)
                time.sleep(delay)
            else:
                break
    raise GeminiServiceUnavailable(
        "Nos serveurs sont momentanément surchargés. Réessayez dans quelques instants."
    ) from last_exc
