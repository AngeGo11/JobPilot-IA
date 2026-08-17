"""
Tests du matching sémantique (phase 4).

Aucun appel réseau : le service d'embedding est remplacé par un générateur
déterministe. Ce qui est vérifié, c'est la mécanique — mode ombre, bascule,
repli, recalcul — et le fait que la similarité classe correctement.
"""
import math
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from administration.models import SiteSettings
from matching.models import JobMatch, JobOffer
from matching.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    SIMILARITY_CEILING,
    SIMILARITY_FLOOR,
    cosine_to_score,
    normalise,
)
from matching.services.scoring import agreement, cosine_similarity, effective_score, semantic_score
from resumes.models import Resume

User = get_user_model()


def vector_from(seed_words, dimensions=EMBEDDING_DIMENSIONS):
    """
    Vecteur déterministe : chaque mot allume quelques dimensions.

    Deux textes partageant des mots produisent donc des vecteurs proches, ce qui
    suffit à tester le classement sans appeler l'API.
    """
    vector = [0.0] * dimensions
    for word in seed_words:
        for offset in range(4):
            index = (hash(word) + offset * 7919) % dimensions
            vector[index] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class CosineTests(TestCase):
    def test_identical_vectors_score_1(self):
        v = vector_from(["python", "django"])
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=5)

    def test_orthogonal_vectors_score_0(self):
        a = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        b = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 2)
        self.assertAlmostEqual(cosine_similarity(a, b), 0.0, places=5)

    def test_mismatched_dimensions_return_none(self):
        self.assertIsNone(cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]))

    def test_none_is_tolerated(self):
        self.assertIsNone(cosine_similarity(None, [1.0]))

    def test_score_conversion_uses_the_measured_range(self):
        """
        Bornes mesurées sur gemini-embedding-001 : deux annonces d'emploi
        françaises ne descendent jamais sous ~0,72, quel que soit le métier.
        """
        self.assertEqual(cosine_to_score(SIMILARITY_FLOOR), 0)
        self.assertEqual(cosine_to_score(SIMILARITY_CEILING), 100)
        self.assertEqual(cosine_to_score(0.80), 50)
        # Hors bornes : on plafonne au lieu de produire un score négatif.
        self.assertEqual(cosine_to_score(0.10), 0)
        self.assertEqual(cosine_to_score(1.00), 100)
        self.assertEqual(cosine_to_score(None), 0)

    def test_unrelated_profession_scores_below_the_alert_threshold(self):
        """
        Le cas qui motive la calibration : un métier sans rapport doit tomber
        loin sous le seuil de 70 %, sinon les alertes emails partent pour des
        offres absurdes.
        """
        self.assertLess(cosine_to_score(0.727), 20)   # boulanger, mesuré
        self.assertLess(cosine_to_score(0.795), 60)   # commercial, mesuré
        self.assertGreater(cosine_to_score(0.864), 80)  # même métier, mesuré


class NormalisationTests(TestCase):
    def test_removes_noise_that_dilutes_the_vector(self):
        texte = (
            "Développeur Python https://exemple.fr/offre "
            "contact@exemple.fr 06 12 34 56 78 Django"
        )
        cleaned = normalise(texte)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("@", cleaned)
        self.assertIn("Développeur Python", cleaned)
        self.assertIn("Django", cleaned)

    def test_empty_input_is_safe(self):
        self.assertEqual(normalise(None), "")
        self.assertEqual(normalise(""), "")


class SemanticRankingTests(TestCase):
    """La similarité doit classer une offre pertinente devant une hors-sujet."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        self.resume = Resume.objects.create(
            user=self.user,
            title="CV",
            file="cvs/a.pdf",
            detected_job_title="Développeur Python",
            detected_skills=["python", "django", "postgresql"],
            extracted_text="python django postgresql backend api",
            embedding=vector_from(["python", "django", "postgresql", "backend", "api"]),
        )
        self.pertinente = JobOffer.objects.create(
            remote_id="OK-1", title="Développeur Python",
            description="python django postgresql api backend",
            embedding=vector_from(["python", "django", "postgresql", "api", "backend"]),
        )
        self.hors_sujet = JobOffer.objects.create(
            remote_id="KO-1", title="Commercial terrain",
            description="prospection vente clients terrain négociation",
            embedding=vector_from(["prospection", "vente", "clients", "terrain", "négociation"]),
        )

    def test_relevant_offer_scores_higher(self):
        bon = semantic_score(self.resume, self.pertinente)
        mauvais = semantic_score(self.resume, self.hors_sujet)

        self.assertGreater(bon, mauvais)
        self.assertGreater(bon, 60, "une offre du même domaine doit ressortir nettement")

    def test_missing_vector_returns_none(self):
        sans_vecteur = JobOffer.objects.create(remote_id="NUL-1", title="Offre récente")
        self.assertIsNone(semantic_score(self.resume, sans_vecteur))


class ShadowModeTests(TestCase):
    """
    Tant que la bascule n'est pas faite, le score sémantique est calculé mais
    n'est jamais montré au candidat.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        resume = Resume.objects.create(user=self.user, title="CV", file="cvs/a.pdf")
        offer = JobOffer.objects.create(remote_id="X-1", title="Poste")
        self.match = JobMatch.objects.create(
            resume=resume, user=self.user, job_offer=offer, score=42, semantic_score=88
        )

    def tearDown(self):
        cache.clear()

    def _set_semantic(self, enabled):
        settings_obj = SiteSettings.load()
        settings_obj.semantic_matching_enabled = enabled
        settings_obj.save()
        cache.clear()

    def test_disabled_shows_keyword_score(self):
        self._set_semantic(False)
        self.assertEqual(effective_score(self.match), 42)
        self.assertEqual(self.match.display_score, 42)

    def test_enabled_shows_semantic_score(self):
        self._set_semantic(True)
        self.assertEqual(effective_score(self.match), 88)
        self.assertEqual(self.match.display_score, 88)

    def test_enabled_falls_back_when_semantic_is_missing(self):
        """
        Une offre tout juste ingérée n'a pas encore de vecteur : mieux vaut le
        score approximatif qu'une case vide.
        """
        self._set_semantic(True)
        self.match.semantic_score = None
        self.assertEqual(effective_score(self.match), 42)

    def test_agreement_reports_the_gap(self):
        self.assertEqual(agreement(self.match), 46)
        self.match.semantic_score = None
        self.assertIsNone(agreement(self.match))


class EmbedTaskTests(TestCase):
    """La vectorisation ne doit ni bloquer ni recalculer inutilement."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="c@example.com", password="MotDePasse!2024")
        self.resume = Resume.objects.create(
            user=self.user, title="CV", file="cvs/a.pdf",
            detected_job_title="Développeur Python",
            detected_skills=["python"],
            extracted_text="python django",
        )

    @patch("matching.services.embeddings.embed")
    def test_task_stores_vector_and_fingerprint(self, embed):
        from matching.tasks import embed_resume_task

        embed.return_value = vector_from(["python", "django"])
        embed_resume_task(self.resume.pk)

        self.resume.refresh_from_db()
        self.assertIsNotNone(self.resume.embedding)
        self.assertTrue(self.resume.embedding_fingerprint)
        self.assertIsNotNone(self.resume.embedded_at)

    @patch("matching.services.embeddings.embed")
    def test_unchanged_content_is_not_re_embedded(self, embed):
        """Un appel d'embedding est facturé : ne pas le refaire pour rien."""
        from matching.tasks import embed_resume_task

        embed.return_value = vector_from(["python", "django"])
        embed_resume_task(self.resume.pk)
        self.assertEqual(embed.call_count, 1)

        embed_resume_task(self.resume.pk)
        self.assertEqual(embed.call_count, 1, "le contenu n'a pas changé")

    @patch("matching.services.embeddings.embed")
    def test_api_failure_leaves_the_resume_usable(self, embed):
        """Un échec de vectorisation ne doit pas casser le CV du candidat."""
        from matching.services.embeddings import EmbeddingUnavailable
        from matching.tasks import embed_resume_task

        embed.side_effect = EmbeddingUnavailable("quota atteint")
        embed_resume_task(self.resume.pk)

        self.resume.refresh_from_db()
        self.assertIsNone(self.resume.embedding)
        self.assertTrue(Resume.objects.filter(pk=self.resume.pk).exists())

    @patch("matching.services.embeddings.embed")
    def test_rescoring_updates_matches(self, embed):
        from matching.tasks import rescore_resume_matches_task

        offer = JobOffer.objects.create(
            remote_id="R-1", title="Développeur Python",
            embedding=vector_from(["python", "django"]),
        )
        match = JobMatch.objects.create(
            resume=self.resume, user=self.user, job_offer=offer, score=30
        )
        self.resume.embedding = vector_from(["python", "django"])
        self.resume.save(update_fields=["embedding"])

        rescore_resume_matches_task(self.resume.pk)

        match.refresh_from_db()
        self.assertIsNotNone(match.semantic_score)
        self.assertGreater(match.semantic_score, 90)
        # Le score par mots-clés ne doit pas avoir bougé.
        self.assertEqual(match.score, 30)
