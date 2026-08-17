"""
Calcul du score de correspondance entre un CV et une offre.

Deux méthodes coexistent volontairement pendant la période de comparaison :

- **mots-clés** (`FranceTravail.calculate_match_score`) : indice de Jaccard ×
  300. Historique, toujours affiché par défaut.
- **sémantique** : similarité cosinus entre les vecteurs du CV et de l'offre.

`SiteSettings.semantic_matching_enabled` décide lequel pilote l'affichage. Tant
qu'il est décoché, le score sémantique est calculé et stocké sans être montré :
on accumule de quoi comparer les deux avant de basculer, plutôt que de changer
d'algorithme sur une intuition.
"""
import logging

from administration.models import SiteSettings
from matching.services.embeddings import cosine_to_score

logger = logging.getLogger(__name__)


def cosine_similarity(a, b):
    """
    Similarité cosinus entre deux vecteurs.

    Les embeddings de Gemini sont normalisés, mais on divise tout de même par
    les normes : une hypothèse non vérifiée sur un service tiers finit toujours
    par se révéler fausse au pire moment.
    """
    if a is None or b is None:
        return None
    if len(a) != len(b):
        logger.warning("Dimensions incompatibles : %s vs %s", len(a), len(b))
        return None

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if not norm_a or not norm_b:
        return None
    return dot / (norm_a * norm_b)


def semantic_score(resume, offer):
    """Score sémantique sur 100, ou `None` si un vecteur manque."""
    similarity = cosine_similarity(
        _as_list(resume.embedding), _as_list(offer.embedding)
    )
    if similarity is None:
        return None
    return cosine_to_score(similarity)


def _as_list(vector):
    """`VectorField` renvoie un tableau numpy ; on repasse en liste de flottants."""
    if vector is None:
        return None
    return [float(x) for x in vector]


def effective_score(match):
    """
    Score qui doit être affiché au candidat pour cette correspondance.

    Retombe sur le score par mots-clés si le sémantique n'est pas disponible :
    une offre tout juste ingérée n'a pas encore de vecteur, et il vaut mieux un
    score approximatif qu'une case vide.
    """
    if not SiteSettings.load().semantic_matching_enabled:
        return match.score
    if match.semantic_score is None:
        return match.score
    return match.semantic_score


def agreement(match):
    """
    Écart entre les deux méthodes, en points.

    Sert au tableau de comparaison du back-office : un écart systématiquement
    faible signifie que la bascule ne changera rien pour les candidats ; un
    écart fort concentré sur les scores hauts est le signal qui justifie de
    basculer.
    """
    if match.semantic_score is None:
        return None
    return match.semantic_score - match.score
