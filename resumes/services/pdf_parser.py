# resumes/pdf_parser.py
import pdfplumber
import re


class PDFParser:
    # Une petite liste de compétences tech pour commencer (tu pourras l'agrandir !)
    KNOWN_SKILLS = {
        'Langages': ['Python', 'Java', 'JavaScript', 'C++', 'PHP', 'Swift', 'SQL','Dart'],
        'Frameworks': ['Django', 'Flask', 'React', 'Angular', 'Vue.js', 'Spring', 'Laravel'],
        'Outils': ['Docker', 'Git', 'Kubernetes', 'AWS', 'Linux', 'Jenkins', 'PostgreSQL', 'MongoDB']
    }

    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.full_text = ""

    def extract_text(self):
        """Étape 1 : Récupérer le texte brut"""
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
        """Transforme le texte brut en données utiles pour la recherche"""
        if not self.full_text:
            self.extract_text()

        return {
            "email": self._extract_email(),
            "phone": self._extract_phone(),
            "skills": self._extract_skills(),  # <--- C'est ici que la magie opère
        }

    def _extract_email(self):
        """Petite fonction bonus pour choper l'email"""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        match = re.search(email_pattern, self.full_text)
        return match.group(0) if match else None


    def _extract_phone(self):
        # Regex simple pour numéros français (06..., +336...)
        phone_pattern = r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}'
        match = re.search(phone_pattern, self.full_text)
        return match.group(0) if match else None

    def _extract_skills(self):
        """Scanne le texte pour trouver des compétences connues"""
        found_skills = []
        text_lower = self.full_text.lower()

        # On parcourt notre dictionnaire de compétences
        for category, skills_list in self.KNOWN_SKILLS.items():
            for skill in skills_list:
                # On cherche le mot exact (avec des boundary \b pour éviter les faux positifs)
                # ex: éviter de trouver "Java" dans "Javascript" si on cherche juste Java
                pattern = r'\b' + re.escape(skill.lower()) + r'\b'
                if re.search(pattern, text_lower):
                    found_skills.append(skill)  # On ajoute le nom propre (ex: Python)

        return list(set(found_skills))  # Supprime les doublons