"""
Tests du suivi des erreurs applicatives.

Le panneau de supervision lisait un fichier de logs. En production, `LOGGING`
bascule sur la sortie standard — App Service n'offre pas de répertoire
inscriptible fiable — donc le panneau n'avait rien à lire et affichait une note
renvoyant vers les journaux de l'hébergeur. Ces erreurs vont désormais en base.
"""
import logging

from django.test import TestCase

from administration.models import ErrorLog
from administration.services import logs
from administration.services.log_handler import DatabaseErrorHandler


class HandlerTests(TestCase):
    def setUp(self):
        ErrorLog.objects.all().delete()
        self.handler = DatabaseErrorHandler()
        self.handler.setLevel(logging.ERROR)
        self.logger = logging.getLogger("tests.erreurs")
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.ERROR)
        self.logger.propagate = False

    def tearDown(self):
        self.logger.handlers = []

    def test_error_is_recorded(self):
        self.logger.error("Quelque chose a cassé")

        entree = ErrorLog.objects.get()
        self.assertEqual(entree.level, "ERROR")
        self.assertEqual(entree.message, "Quelque chose a cassé")
        self.assertEqual(entree.occurrences, 1)

    def test_traceback_is_captured(self):
        try:
            raise ValueError("échec interne")
        except ValueError:
            self.logger.exception("Traitement interrompu")

        entree = ErrorLog.objects.get()
        self.assertIn("ValueError", entree.traceback)
        self.assertIn("échec interne", entree.traceback)

    def test_repeated_error_is_grouped(self):
        """
        Une même erreur qui se répète incrémente un compteur. Sans cela, une
        boucle en échec remplirait la table de milliers de lignes identiques et
        masquerait les autres incidents.
        """
        for _ in range(5):
            self.logger.error("Appel API refusé")

        entree = ErrorLog.objects.get()
        self.assertEqual(entree.occurrences, 5)
        self.assertTrue(entree.is_recurring)

    def test_variable_identifiers_do_not_split_the_group(self):
        """« commande 4271 » et « commande 9999 » sont la même erreur."""
        for numero in (4271, 9999, 12345):
            self.logger.error("Échec pour la commande %s", numero)

        self.assertEqual(ErrorLog.objects.count(), 1)
        self.assertEqual(ErrorLog.objects.get().occurrences, 3)

    def test_distinct_errors_stay_distinct(self):
        self.logger.error("Première panne")
        self.logger.error("Panne totalement différente")

        self.assertEqual(ErrorLog.objects.count(), 2)

    def test_database_loggers_are_ignored(self):
        """Journaliser une panne de base dans la base ne peut pas fonctionner."""
        db_logger = logging.getLogger("django.db.backends")
        db_logger.handlers = [self.handler]
        db_logger.propagate = False

        db_logger.error("connexion perdue")

        self.assertEqual(ErrorLog.objects.count(), 0)
        db_logger.handlers = []

    def test_handler_never_raises(self):
        """
        Un handler qui lève transforme un incident journalisé en incident
        visible par l'utilisateur.
        """
        from unittest.mock import patch

        with patch.object(ErrorLog.objects, "filter", side_effect=RuntimeError("base HS")):
            self.logger.error("erreur pendant que la base est HS")  # ne doit pas lever


class PanelTests(TestCase):
    def test_empty_state_explains_itself(self):
        ErrorLog.objects.all().delete()
        entrees, note = logs.recent_errors()

        self.assertEqual(entrees, [])
        self.assertIn("Aucune erreur enregistrée", note)

    def test_hotspots_sum_occurrences(self):
        ErrorLog.objects.create(module="matching", message="a", fingerprint="1", occurrences=7)
        ErrorLog.objects.create(module="matching", message="b", fingerprint="2", occurrences=3)
        ErrorLog.objects.create(module="resumes", message="c", fingerprint="3", occurrences=4)

        points = logs.error_hotspots()

        self.assertEqual(points[0], ("matching", 10))
        self.assertEqual(points[1], ("resumes", 4))

    def test_purge_removes_only_old_entries(self):
        from datetime import timedelta

        from django.utils import timezone

        from matching.tasks import purge_error_logs_task

        vieille = ErrorLog.objects.create(module="m", message="vieux", fingerprint="v")
        ErrorLog.objects.filter(pk=vieille.pk).update(
            last_seen_at=timezone.now() - timedelta(days=60)
        )
        recente = ErrorLog.objects.create(module="m", message="recent", fingerprint="r")

        purge_error_logs_task(days=30)

        self.assertFalse(ErrorLog.objects.filter(pk=vieille.pk).exists())
        self.assertTrue(ErrorLog.objects.filter(pk=recente.pk).exists())
