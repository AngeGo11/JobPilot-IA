"""
Représentation vectorielle des CV et des offres.

Pourquoi : `calculate_match_score()` compare deux sacs de mots (indice de
Jaccard × 300). Un CV de développeur ressort donc face à une offre de
commercial dès qu'ils partagent du vocabulaire d'entreprise — « équipe »,
« projet », « autonomie » — alors qu'un CV parlant de « Python » ne matche pas
une offre parlant de « Django » puisque les mots diffèrent.

Un embedding place le texte dans un espace où la proximité traduit le sens et
non les mots exacts. La similarité cosinus entre deux vecteurs devient le score.
"""
import hashlib
import logging
import os
import re

from django.conf import settings

from utils.gemini_safe import call_gemini_with_retry, ensure_gemini_rate_limit

logger = logging.getLogger(__name__)

# Modèle vérifié auprès de l'API (`client.models.list()`) : `text-embedding-004`
# n'est plus exposé, `gemini-embedding-001` le remplace. Il produit 3072
# dimensions par défaut ; on demande explicitement 768, valeur figée dans les
# migrations — la changer imposerait de recalculer tous les vecteurs existants.
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

# Au-delà, l'API tronque de toute façon ; on coupe avant pour éviter d'envoyer
# des CV entiers dont seule la première partie porte le signal utile.
MAX_CHARS = 8000


class EmbeddingUnavailable(Exception):
    """Le service d'embedding n'a pas pu produire de vecteur."""


def normalise(text):
    """
    Nettoyage léger avant vectorisation.

    On retire les URL, les adresses email et les blocs de chiffres : ils
    n'apportent pas de sens métier et diluent le vecteur. On ne retire pas les
    « stopwords » — contrairement au score par mots-clés, le modèle les utilise
    pour comprendre la structure des phrases.
    """
    if not text:
        return ""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\S+@\S+\.\S+", " ", text)
    text = re.sub(r"\b\d[\d\s./-]{6,}\b", " ", text)  # téléphones, références
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:MAX_CHARS]


def content_fingerprint(text):
    """
    Empreinte du texte vectorisé.

    Stockée à côté du vecteur, elle évite de rappeler l'API — et de la facturer —
    quand le contenu n'a pas changé depuis le dernier calcul.
    """
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def _client():
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        raise EmbeddingUnavailable("GEMINI_API_KEY manquante.")
    return genai.Client(api_key=api_key)


def embed(text, *, user_id=None, task_type="SEMANTIC_SIMILARITY"):
    """
    Retourne le vecteur du texte, ou lève `EmbeddingUnavailable`.

    Passe par les mêmes garde-fous de débit que les autres appels Gemini :
    l'embedding consomme le même quota que la génération de texte.
    """
    cleaned = normalise(text)
    if not cleaned:
        raise EmbeddingUnavailable("Texte vide : rien à vectoriser.")

    ensure_gemini_rate_limit(user_id=user_id)
    client = _client()

    def call():
        return client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=cleaned,
            config={
                "task_type": task_type,
                "output_dimensionality": EMBEDDING_DIMENSIONS,
            },
        )

    try:
        response = call_gemini_with_retry(call)
    except Exception as exc:
        raise EmbeddingUnavailable(str(exc)) from exc

    vector = _extract_vector(response)
    if vector is None or len(vector) != EMBEDDING_DIMENSIONS:
        raise EmbeddingUnavailable(
            f"Vecteur inattendu : {0 if vector is None else len(vector)} dimensions "
            f"au lieu de {EMBEDDING_DIMENSIONS}."
        )
    return vector


def _extract_vector(response):
    """
    Extrait la liste de flottants de la réponse.

    Le SDK a changé de forme entre versions (`embeddings[0].values` aujourd'hui,
    `embedding.values` auparavant) ; on accepte les deux plutôt que de casser à
    la prochaine montée de version.
    """
    embeddings = getattr(response, "embeddings", None)
    if embeddings:
        first = embeddings[0]
        return list(getattr(first, "values", first) or [])
    single = getattr(response, "embedding", None)
    if single is not None:
        return list(getattr(single, "values", single) or [])
    return None


# Bornes de calibration, mesurées sur `gemini-embedding-001` avec des textes
# d'offres réels en français (CV de développeur backend contre six offres) :
#
#   texte identique .................. 1,000
#   même métier, mots différents ..... 0,864
#   métier proche .................... 0,845
#   commercial (vocabulaire commun) .. 0,795
#   autre métier technique ........... 0,752
#   métier sans rapport .............. 0,727
#
# Le modèle ne descend jamais sous ~0,72 entre deux textes du même genre —
# deux annonces d'emploi partagent registre et tournures quelles que soient
# leurs professions. Une conversion naïve depuis 0 donnerait donc 72 % à un CV
# de développeur face à une offre de boulanger, au-dessus du seuil d'alerte.
# On étire la plage réellement discriminante.
SIMILARITY_FLOOR = 0.72     # aucun rapport → 0
SIMILARITY_CEILING = 0.88   # même métier → 100


def cosine_to_score(similarity):
    """
    Convertit une similarité cosinus en score sur 100.

    Voir SIMILARITY_FLOOR / SIMILARITY_CEILING pour la base empirique. Ces
    bornes dépendent du modèle : les remesurer si EMBEDDING_MODEL change.
    """
    if similarity is None:
        return 0
    clamped = max(SIMILARITY_FLOOR, min(SIMILARITY_CEILING, float(similarity)))
    return int(round((clamped - SIMILARITY_FLOOR) / (SIMILARITY_CEILING - SIMILARITY_FLOOR) * 100))


def offer_text(offer):
    """Texte représentatif d'une offre : l'intitulé pèse autant que la description."""
    parts = [offer.title or "", offer.title or "", offer.company_name or "", offer.description or ""]
    return " ".join(part for part in parts if part)


def resume_text(resume):
    """
    Texte représentatif d'un CV.

    Le poste détecté et les compétences sont répétés en tête : ils condensent
    l'intention du candidat, que le corps du CV noie souvent sous les
    descriptions de missions passées.
    """
    skills = " ".join(resume.detected_skills or [])
    parts = [
        resume.detected_job_title or "",
        resume.detected_job_title or "",
        skills,
        resume.extracted_text or "",
    ]
    return " ".join(part for part in parts if part)
