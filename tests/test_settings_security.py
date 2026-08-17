"""
Tests de non-régression pour des correctifs de sécurité au niveau de JobPilot/settings/base.py.

Couvre :
- AUTH_PASSWORD_VALIDATORS : longueur minimale de mot de passe portée à 12 caractères.
- ALLOWED_HOSTS : logique dev (['*']) vs prod (_PROD_SECURITY -> domaine restreint).

Note sur ALLOWED_HOSTS : la valeur réelle utilisée par Django (django.conf.settings)
est figée au démarrage du process de test à partir des variables d'environnement
présentes à ce moment-là (DEBUG/ENVIRONMENT du .env, généralement dev). On ne peut
donc pas changer cette valeur "en live" sans redémarrer Django. Pour verrouiller la
LOGIQUE de calcul (et pas seulement la valeur figée au démarrage), on recharge le
module JobPilot.settings.base (un simple module Python, indépendant de l'objet
django.conf.settings déjà initialisé) avec des variables d'environnement modifiées,
puis on restaure l'état original. Cela ne perturbe pas le reste de la suite de tests
car django.conf.settings a déjà capturé ses propres attributs une fois pour toutes
au démarrage de Django.
"""
import importlib
import os
from unittest import mock

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

# On vise `base` : c'est là que vit la logique de calcul. Le paquet
# `JobPilot.settings` ne réexporte pas les noms préfixés d'un underscore.
import JobPilot.settings.base as settings_module


class PasswordMinimumLengthSettingTests(SimpleTestCase):
    """Verrouille : MinimumLengthValidator avec min_length=12 dans AUTH_PASSWORD_VALIDATORS."""

    def test_settings_declares_min_length_12(self):
        min_length_validators = [
            v for v in settings_module.AUTH_PASSWORD_VALIDATORS
            if v["NAME"] == "django.contrib.auth.password_validation.MinimumLengthValidator"
        ]
        self.assertEqual(len(min_length_validators), 1)
        self.assertEqual(min_length_validators[0]["OPTIONS"]["min_length"], 12)

    def test_eight_char_password_rejected_end_to_end(self):
        with self.assertRaises(ValidationError):
            validate_password("Passwd1!")  # 8 caractères

    def test_twelve_plus_char_password_accepted_end_to_end(self):
        validate_password("Xk7$vLm9#pQz2!Rt")  # > 12 caractères, non trivial


class AllowedHostsLogicTests(SimpleTestCase):
    """Verrouille la logique de calcul d'ALLOWED_HOSTS selon _PROD_SECURITY, en
    rechargeant le module de settings (pas l'objet django.conf.settings actif) avec
    des variables d'environnement contrôlées."""

    def _reload_settings_with_env(self, env_overrides):
        original_environ = dict(os.environ)
        try:
            os.environ.update(env_overrides)
            importlib.reload(settings_module)
            return settings_module.ALLOWED_HOSTS, settings_module._PROD_SECURITY
        finally:
            os.environ.clear()
            os.environ.update(original_environ)
            # On recharge une dernière fois pour restaurer l'état du module tel
            # qu'il était avant ce test (évite de fausser les tests suivants qui
            # importeraient à nouveau JobPilot.settings).
            importlib.reload(settings_module)

    def test_dev_allows_any_host(self):
        allowed_hosts, prod_security = self._reload_settings_with_env(
            {"DEBUG": "true", "ENVIRONMENT": "development"}
        )
        self.assertFalse(prod_security)
        self.assertEqual(allowed_hosts, ["*"])

    def test_prod_restricts_hosts_to_site_domain(self):
        allowed_hosts, prod_security = self._reload_settings_with_env(
            {"DEBUG": "false", "ENVIRONMENT": "production", "SITE_URL": "https://jobpilot-ai.fr"}
        )
        self.assertTrue(prod_security)
        self.assertEqual(allowed_hosts, ["jobpilot-ai.fr", "www.jobpilot-ai.fr"])

    def test_debug_true_in_production_env_keeps_wildcard(self):
        """Si DEBUG=True, même avec ENVIRONMENT=production, on reste en mode dev
        (garde-fou : _PROD_SECURITY = (not DEBUG) and (ENVIRONMENT == 'production'))."""
        allowed_hosts, prod_security = self._reload_settings_with_env(
            {"DEBUG": "true", "ENVIRONMENT": "production"}
        )
        self.assertFalse(prod_security)
        self.assertEqual(allowed_hosts, ["*"])
