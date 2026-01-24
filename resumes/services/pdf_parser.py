# resumes/pdf_parser.py
import pdfplumber
import re


class PDFParser:
    """
    Service pour extraire le texte brut d'un PDF et des informations basiques (email, téléphone).
    L'extraction des compétences et du titre de poste est maintenant gérée par AIParser (Gemini).
    """
    
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.full_text = ""

    def extract_text(self):
        """Étape 1 : Récupérer le texte brut du PDF"""
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        self.full_text += text + "\n"
            return self.full_text
        except Exception as e:
            print(f"Erreur lecture PDF : {e}")
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