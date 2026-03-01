# resumes/pdf_parser.py
import io
import pdfplumber
import re
import logging


class PDFParser:
    """
    Service pour extraire le texte brut d'un PDF et des informations basiques (email, téléphone).
    L'extraction des compétences et du titre de poste est maintenant gérée par AIParser (Gemini).
    Accepte soit un chemin de fichier local (str/Path), soit des bytes (ex. fichier depuis Azure Blob).
    """

    def __init__(self, pdf_source):
        """
        pdf_source: chemin local (str/pathlib.Path) ou contenu du PDF en bytes.
        Utiliser des bytes pour les fichiers en stockage cloud (Azure Blob, S3, etc.).
        """
        self.pdf_source = pdf_source
        self.full_text = ""

    def _open_pdf(self):
        """Ouvre le PDF depuis un chemin ou depuis la mémoire (bytes)."""
        if isinstance(self.pdf_source, bytes):
            return pdfplumber.open(io.BytesIO(self.pdf_source))
        return pdfplumber.open(self.pdf_source)

    def extract_text(self):
        """Étape 1 : Récupérer le texte brut du PDF"""
        try:
            with self._open_pdf() as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        self.full_text += text + "\n"
            return self.full_text
        except Exception as e:
            logging.info(f"Erreur lecture PDF : {e}")
            return None

    def parse_data(self):
        """
        Extrait les informations basiques du CV (email, téléphone).
        Les compétences et le titre de poste sont maintenant extraits par AIParser (Gemini).
        """
        if not self.full_text:
            self.extract_text()

        return {
            "email": self._extract_email(),
            "phone": self._extract_phone(),
        }

    def _extract_email(self):
        """Extrait l'adresse email du texte du CV"""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        match = re.search(email_pattern, self.full_text)
        return match.group(0) if match else None

    def _extract_phone(self):
        """Extrait le numéro de téléphone français du texte du CV"""
        phone_pattern = r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}'
        match = re.search(phone_pattern, self.full_text)
        return match.group(0) if match else None