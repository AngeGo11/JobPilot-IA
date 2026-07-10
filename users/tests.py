"""
Tests de non-régression pour les correctifs de sécurité de l'authentification.

Couvre :
- UserLoginForm.email : le champ est un forms.EmailField (et non plus CharField),
  donc un email mal formé doit être rejeté par la validation du formulaire, avant
  même toute tentative d'authentification.
- AUTH_PASSWORD_VALIDATORS : MinimumLengthValidator exige désormais 12 caractères
  minimum (voir JobPilot/settings.py).
"""
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.test import RequestFactory, TestCase

from users.forms import UserLoginForm
from users.models import CustomUser


class UserLoginFormEmailFieldTests(TestCase):
    """Verrouille le correctif : email est un EmailField, donc un email malformé
    est rejeté à la validation du formulaire (avant toute authentification)."""

    def setUp(self):
        self.factory = RequestFactory()

    def _build_form(self, email, password="whatever-password"):
        request = self.factory.post("/login/")
        return UserLoginForm(request, data={"email": email, "password": password})

    def test_malformed_email_is_rejected(self):
        form = self._build_form("pas-un-email")
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_malformed_email_missing_domain_is_rejected(self):
        form = self._build_form("user@")
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_email_field_is_an_email_field_instance(self):
        """Vérifie explicitement que le champ est bien un EmailField (et non un CharField)."""
        form = UserLoginForm(self.factory.post("/login/"))
        self.assertIsInstance(form.fields["email"], forms.EmailField)

    def test_well_formed_email_passes_field_validation(self):
        """Un email syntaxiquement valide passe la validation de champ (même si les
        identifiants sont ensuite refusés par authenticate() faute d'utilisateur)."""
        form = self._build_form("someone@example.com", password="whatever-password")
        form.is_valid()
        # Le champ email lui-même ne doit pas être en erreur de format.
        self.assertNotIn("email", form.errors)


class PasswordValidatorMinimumLengthTests(TestCase):
    """Verrouille le correctif : AUTH_PASSWORD_VALIDATORS impose désormais un
    mot de passe d'au moins 12 caractères (MinimumLengthValidator min_length=12)."""

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("short8ch")

    def test_password_of_eleven_chars_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_password("Abcdefghi1!"[:11])

    def test_password_of_twelve_or_more_chars_is_accepted(self):
        # Mot de passe non trivial (pas commun, pas purement numérique, >= 12 caractères).
        strong_password = "Xk7$vLm9#pQz2!Rt"
        # Ne doit lever aucune exception.
        validate_password(strong_password)

    def test_password_creation_via_create_user_enforces_length(self):
        """S'assure que le validateur s'applique bien dans le flux réel de création
        d'utilisateur (via validate_password appelé manuellement, comme le ferait un
        formulaire d'inscription)."""
        user = CustomUser(email="newuser@example.com", first_name="Jean", last_name="Dupont")
        with self.assertRaises(ValidationError):
            validate_password("short123", user=user)

        # Un mot de passe suffisamment long et non trivial passe la validation.
        validate_password("Xk7$vLm9#pQz2!Rt", user=user)
