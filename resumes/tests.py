from unittest.mock import patch, MagicMock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from resumes.forms import MAX_RESUME_SIZE, ResumeUploadForm
from resumes.models import Resume
from resumes.services.pseudonymizer import Pseudonymizer
from resumes.services.ai_parser import AIParser
from users.models import CustomUser

# Contenu minimal d'un PDF valide : un vrai PDF commence par cette signature (magic bytes).
MINIMAL_PDF_CONTENT = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF"
)


class PseudonymizerTests(TestCase):
    def setUp(self):
        self.cv_text = (
            "Jean Dupont\n"
            "Développeur Python\n"
            "Email : jean.dupont@example.com\n"
            "Téléphone : 06 12 34 56 78\n"
            "Compétences : Python, Django, Docker\n"
        )

    def test_pseudonymize_removes_email_and_phone(self):
        pseudonymizer = Pseudonymizer()
        safe_text = pseudonymizer.pseudonymize(self.cv_text)

        self.assertNotIn("jean.dupont@example.com", safe_text)
        self.assertNotIn("06 12 34 56 78", safe_text)
        self.assertIn("[EMAIL_1]", safe_text)
        self.assertIn("[TEL_1]", safe_text)
        # Les données utiles au matching restent intactes
        self.assertIn("Python, Django, Docker", safe_text)

    def test_pseudonymize_removes_name_first_line(self):
        pseudonymizer = Pseudonymizer()
        safe_text = pseudonymizer.pseudonymize(self.cv_text)

        self.assertNotIn("Jean Dupont", safe_text)
        self.assertIn("[NOM_1]", safe_text)

    def test_depseudonymize_restores_original(self):
        pseudonymizer = Pseudonymizer()
        safe_text = pseudonymizer.pseudonymize(self.cv_text)
        restored = pseudonymizer.depseudonymize(safe_text)

        self.assertEqual(restored, self.cv_text.rstrip("\n"))


@override_settings(GEMINI_API_KEY="fake-key-for-tests")
class AIParserPseudonymizationTests(TestCase):
    @patch("resumes.services.ai_parser.genai")
    def test_prompt_sent_to_gemini_has_no_raw_pii(self, mock_genai):
        mock_response = MagicMock()
        mock_response.text = '{"job_title": "Développeur Python", "skills": ["Python", "Django"]}'
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        cv_text = (
            "Jean Dupont\n"
            "Email : jean.dupont@example.com\n"
            "Téléphone : 06 12 34 56 78\n"
            "Python, Django, Docker\n"
        )

        parser = AIParser()
        result = parser.extract_job_info(cv_text, user_id=None)

        sent_prompt = mock_client.models.generate_content.call_args.kwargs["contents"]
        self.assertNotIn("jean.dupont@example.com", sent_prompt)
        self.assertNotIn("06 12 34 56 78", sent_prompt)
        self.assertNotIn("Jean Dupont", sent_prompt)
        self.assertIn("Python, Django, Docker", sent_prompt)

        self.assertEqual(result["job_title"], "Développeur Python")
        self.assertCountEqual(result["skills"], ["Python", "Django"])


class ResumeUploadFormTests(TestCase):
    """
    Verrouille le correctif de sécurité de ResumeUploadForm.clean_file :
    rejet des fichiers non-PDF (extension, content_type, magic bytes) et des
    fichiers dépassant MAX_RESUME_SIZE (10 Mo).
    """

    def _build_form(self, uploaded_file, title="Mon CV"):
        return ResumeUploadForm(data={"title": title}, files={"file": uploaded_file})

    def test_valid_pdf_is_accepted(self):
        """Un vrai petit PDF (bonne extension, bon content_type, bons magic bytes) est accepté."""
        uploaded = SimpleUploadedFile(
            "cv.pdf", MINIMAL_PDF_CONTENT, content_type="application/pdf"
        )
        form = self._build_form(uploaded)
        self.assertTrue(form.is_valid(), form.errors)

    def test_fake_pdf_with_text_content_is_rejected(self):
        """Extension .pdf et content_type PDF, mais contenu texte (pas de magic bytes %PDF-)."""
        fake_content = b"Ceci n'est pas du tout un PDF, juste du texte brut."
        uploaded = SimpleUploadedFile(
            "faux.pdf", fake_content, content_type="application/pdf"
        )
        form = self._build_form(uploaded)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_wrong_extension_is_rejected(self):
        """Un fichier exécutable (mauvaise extension .exe) est rejeté même avec un contenu PDF valide."""
        uploaded = SimpleUploadedFile(
            "malware.exe", MINIMAL_PDF_CONTENT, content_type="application/octet-stream"
        )
        form = self._build_form(uploaded)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)
        self.assertIn("Seuls les fichiers PDF sont acceptés.", form.errors["file"])

    def test_exe_renamed_to_pdf_is_rejected(self):
        """Un .exe renommé en .pdf (bonne extension apparente) mais avec un content_type/contenu
        non-PDF doit être rejeté grâce aux vérifications de content_type et de magic bytes."""
        fake_exe_content = b"MZ\x90\x00\x03\x00\x00\x00binary-exe-content-not-a-pdf"
        uploaded = SimpleUploadedFile(
            "renamed_malware.pdf", fake_exe_content, content_type="application/x-msdownload"
        )
        form = self._build_form(uploaded)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_oversized_file_is_rejected(self):
        """Un fichier PDF valide mais dépassant MAX_RESUME_SIZE (10 Mo) doit être rejeté."""
        oversized_content = MINIMAL_PDF_CONTENT + b"0" * (MAX_RESUME_SIZE + 1 - len(MINIMAL_PDF_CONTENT))
        self.assertGreater(len(oversized_content), MAX_RESUME_SIZE)
        uploaded = SimpleUploadedFile(
            "big.pdf", oversized_content, content_type="application/pdf"
        )
        form = self._build_form(uploaded)
        self.assertFalse(form.is_valid())
        self.assertIn("file", form.errors)

    def test_file_at_exact_limit_is_accepted(self):
        """Un fichier PDF valide dont la taille est exactement MAX_RESUME_SIZE reste accepté."""
        padding_len = MAX_RESUME_SIZE - len(MINIMAL_PDF_CONTENT)
        exact_content = MINIMAL_PDF_CONTENT + b"0" * padding_len
        self.assertEqual(len(exact_content), MAX_RESUME_SIZE)
        uploaded = SimpleUploadedFile(
            "exact.pdf", exact_content, content_type="application/pdf"
        )
        form = self._build_form(uploaded)
        self.assertTrue(form.is_valid(), form.errors)


class ResumeModelFileExtensionValidatorTests(TestCase):
    """Vérifie que Resume.file rejette, au niveau modèle, les extensions non autorisées
    grâce au FileExtensionValidator(allowed_extensions=['pdf'])."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="candidate@example.com", password="a-very-strong-password-123"
        )

    def test_model_rejects_non_pdf_extension(self):
        resume = Resume(
            user=self.user,
            title="CV suspect",
            file=SimpleUploadedFile("cv.txt", b"contenu quelconque"),
        )
        with self.assertRaises(ValidationError):
            resume.full_clean()

    def test_model_accepts_pdf_extension(self):
        resume = Resume(
            user=self.user,
            title="CV valide",
            file=SimpleUploadedFile("cv.pdf", MINIMAL_PDF_CONTENT),
        )
        try:
            resume.full_clean()
        except ValidationError as exc:
            self.fail(f"full_clean() a levé une ValidationError inattendue : {exc}")
