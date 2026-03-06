import os
from io import BytesIO
from typing import Optional

from google import genai
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from utils.gemini_safe import ensure_gemini_rate_limit, call_gemini_with_retry


class AILetterGenerator:
    """
    Service responsable de la génération de lettres de motivation
    en utilisant la nouvelle API Google Gemini (google.genai).
    """

    def __init__(self):
        """
        Initialise le service avec la clé API Google Gemini.
        """
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY n'est pas définie dans les variables d'environnement. "
                "Ajoutez-la dans votre fichier .env"
            )

        # Initialisation propre du nouveau client
        self.client = genai.Client(api_key=api_key)
        # On définit le modèle par défaut ici pour ne pas le répéter
        self.model_name = "gemini-2.5-flash"

    def generate_cover_letter(
            self,
            resume,
            job_match,
            custom_instructions: Optional[str] = None,
            tone: str = "professional",
            user_id: Optional[int] = None,
    ) -> str:

        # Validation des données
        if not resume or not resume.extracted_text:
            raise ValueError("Le CV doit contenir du texte extrait (extracted_text)")

        if not job_match or not job_match.job_offer:
            raise ValueError("Le match doit contenir une offre d'emploi")

        # Préparation des données
        cv_text = resume.extracted_text
        job_offer = job_match.job_offer
        job_desc = job_offer.description or ""
        company = job_offer.company_name or "cette entreprise"
        title = job_offer.title or "ce poste"

        # Mapping des tons
        tone_descriptions = {
            'professional': 'professionnel, motivé, mais pas arrogant',
            'enthusiastic': 'enthousiaste, dynamique et passionné',
            'formal': 'formel, respectueux et conventionnel',
        }
        tone_description = tone_descriptions.get(tone, tone_descriptions['professional'])

        # Construction du prompt
        prompt = f"""Tu es un expert en recrutement et coach de carrière spécialisé dans la tech.
        Ta mission est de rédiger une lettre de motivation percutante pour une candidature.
        
        CONTEXTE :
        - Le candidat postule pour le poste de : {title}
        - Chez l'entreprise : {company}
        
        DOCUMENT 1 : LE CV DU CANDIDAT
        ---
        {cv_text}
        ---
        
        DOCUMENT 2 : L'OFFRE D'EMPLOI
        ---
        {job_desc}
        ---
        
        CONSIGNES DE RÉDACTION :
        1. Analyse le CV pour identifier les compétences qui matchent précisément avec l'offre.
        2. Adopte un ton {tone_description}.
        3. La structure doit être :
           - Accroche : Pourquoi cette entreprise et ce poste ?
           - Corps : Mes compétences clés (Hard Skills) en lien avec vos besoins.
           - Soft Skills : Ma valeur ajoutée humaine.
           - Conclusion : Appel à l'action (demande d'entretien).
        4. Ne pas inventer d'expériences non présentes dans le CV.
        5. Rédige la lettre directement, sans phrase d'intro du type "Voici la lettre".
        6. La lettre doit faire environ 250-350 mots.
        7. Utilise "Madame, Monsieur" en début de lettre.
        8. Signe avec "Cordialement" ou "Bien cordialement".
        """

        if custom_instructions:
            prompt += f"\n\nINSTRUCTIONS PERSONNALISÉES :\n{custom_instructions}\n"

        try:
            ensure_gemini_rate_limit(user_id)

            # NOUVELLE SYNTAXE D'APPEL ICI :
            response = call_gemini_with_retry(
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
            )

            # L'extraction est maintenant super simple
            return response.text.strip()

        except Exception as e:
            raise Exception(f"Erreur lors de la génération de la lettre de motivation : {str(e)}")

    def refine_cover_letter(
            self,
            existing_letter: str,
            instructions: str,
            user_id: Optional[int] = None,
    ) -> str:

        if not existing_letter:
            raise ValueError("La lettre de motivation ne peut pas être vide")

        if not instructions:
            raise ValueError("Les instructions d'amélioration sont requises")

        prompt = f"""Tu es un expert en rédaction de lettres de motivation professionnelles.
        Ta mission est d'améliorer cette lettre de motivation selon les instructions fournies, tout en conservant son essence et ses informations factuelles.
        
        LETTRE ACTUELLE :
        ---
        {existing_letter}
        ---
        
        INSTRUCTIONS D'AMÉLIORATION :
        {instructions}
        
        RÈGLES STRICTES À SUIVRE :
        1. Conserve TOUTES les informations factuelles (noms d'entreprises, dates, compétences mentionnées)
        2. Garde la structure générale de la lettre (accroche, développement, conclusion)
        3. Respecte le ton existant sauf si les instructions demandent explicitement de le changer
        4. Applique uniquement les améliorations demandées dans les instructions
        5. Corrige les fautes d'orthographe et de grammaire automatiquement
        6. Améliore la fluidité et la clarté du texte
        7. Retourne UNIQUEMENT la lettre améliorée, sans commentaires, sans explications, sans préambule
        8. La lettre doit commencer directement par "Madame, Monsieur" ou l'équivalent
        9. La lettre doit se terminer par une formule de politesse appropriée
        
        Retourne maintenant la lettre améliorée :
        """

        try:
            ensure_gemini_rate_limit(user_id)

            # NOUVELLE SYNTAXE D'APPEL ICI :
            response = call_gemini_with_retry(
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
            )

            return response.text.strip()

        except Exception as e:
            raise Exception(f"Erreur lors de l'amélioration de la lettre : {str(e)}")

    def _build_refinement_instructions(self, custom_instructions: str, improvement_type: str) -> str:
        """
        Construit les instructions d'amélioration finales en combinant le type et les instructions personnalisées.

        Args :
            custom_instructions : Instructions personnalisées de l'utilisateur
            improvement_type : Type d'amélioration prédéfini

        Returns :
            str : Instructions complètes pour l'amélioration
        """
        # Instructions de base selon le type
        type_instructions = {
            'grammar': """Corrige toutes les fautes d'orthographe, de grammaire et de syntaxe.
                Améliore la ponctuation et la mise en forme.
                Assure-toi que le texte est parfaitement écrit en français.""",

            'tone': """Rends le ton plus professionnel et formel.
                Utilise un langage plus soutenu et respectueux.
                Évite les expressions trop familières ou décontractées.""",

            'length': """Optimise la longueur de la lettre pour qu'elle soit concise mais complète.
                Élimine les redondances et les phrases inutiles.
                Garde uniquement les informations essentielles et percutantes.""",

            'structure': """Améliore la structure et l'organisation de la lettre.
                Assure-toi que chaque paragraphe a un objectif clair.
                Rends les transitions entre les paragraphes plus fluides.
                Vérifie que la lettre suit une logique claire : accroche, développement, conclusion.""",
            'custom': ''  # Pas d'instructions prédéfinies, on utilise uniquement les instructions personnalisées
        }

        base_instructions = type_instructions.get(improvement_type, '')

        # Combiner les instructions
        if improvement_type == 'custom':
            # Si c'est personnalisé, on utilise uniquement les instructions de l'utilisateur
            final_instructions = custom_instructions
        elif custom_instructions:
            # Si on a un type ET des instructions personnalisées, on combine
            final_instructions = f"""{base_instructions}
                De plus, applique ces instructions personnalisées :
                {custom_instructions}"""
        else:
            # Si seulement le type est fourni
            final_instructions = base_instructions

        return final_instructions

    def validate_api_connection(self, user_id: Optional[int] = None) -> bool:
        try:
            ensure_gemini_rate_limit(user_id)
            test_prompt = "Réponds simplement 'OK' si tu reçois ce message."

            # NOUVELLE SYNTAXE D'APPEL ICI :
            response = call_gemini_with_retry(
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=test_prompt
                )
            )

            # On utilise la variable : on vérifie qu'on a bien reçu un texte
            if response.text and len(response.text.strip()) > 0:
                return True

            # Si l'IA renvoie du vide, c'est qu'il y a un souci
            return False

        except Exception as e:
            raise Exception(f"Impossible de se connecter à l'API Gemini : {str(e)}")

    def export_to_pdf(
            self,
            cover_letter_content: str,
            user_name: Optional[str] = None,
            user_email: Optional[str] = None,
            user_address: Optional[str] = None,
            job_title: Optional[str] = None,
            company_name: Optional[str] = None,
            recipient_name: Optional[str] = None
    ) -> BytesIO:
        """
        Exporte une lettre de motivation en format PDF professionnel.

        Args:
            cover_letter_content : Contenu de la lettre de motivation
            user_name : Nom complet de l'utilisateur (optionnel)
            user_email : Email de l'utilisateur (optionnel)
            user_address : Adresse de l'utilisateur (optionnel)
            job_title: Titre du poste (optionnel)
            company_name: Nom de l'entreprise (optionnel)
            recipient_name: Nom du destinataire (optionnel, par défaut "Madame, Monsieur")

        Returns:
            BytesIO: Buffer contenant le PDF généré

        Raises:
            ValueError: Si le contenu de la lettre est vide
            Exception: Si la génération du PDF échoue
        """
        if not cover_letter_content or not cover_letter_content.strip():
            raise ValueError("Le contenu de la lettre de motivation ne peut pas être vide")

        # Créer un buffer en mémoire pour le PDF
        buffer = BytesIO()

        # Créer le document PDF
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm
        )

        # Styles pour le PDF
        styles = getSampleStyleSheet()

        # Style pour l'en-tête (nom, adresse, etc.)
        header_style = ParagraphStyle(
            'CustomHeader',
            parent=styles['Normal'],
            fontSize=10,
            textColor='black',
            alignment=TA_LEFT,
            spaceAfter=12,
        )

        # Style pour le titre (objet)
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading2'],
            fontSize=12,
            textColor='black',
            alignment=TA_LEFT,
            spaceAfter=12,
            spaceBefore=12,
        )

        # Style pour le corps de la lettre
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            textColor='black',
            alignment=TA_JUSTIFY,
            spaceAfter=12,
            leading=14,
        )

        # Style pour la signature
        signature_style = ParagraphStyle(
            'CustomSignature',
            parent=styles['Normal'],
            fontSize=11,
            textColor='black',
            alignment=TA_LEFT,
            spaceBefore=24,
        )

        # Construire le contenu du PDF
        story = []

        # Objet
        if job_title:
            story.append(Paragraph(f"<b>Objet : Candidature pour le poste de {job_title}</b>", title_style))
            story.append(Spacer(1, 0.3 * cm))

        # Corps de la lettre
        # Convertir le texte en paragraphes (séparés par des sauts de ligne doubles)
        paragraphs = cover_letter_content.split('\n\n')

        for para in paragraphs:
            para = para.strip()
            if para:
                # Remplacer les sauts de ligne simples par <br/>
                para_html = para.replace('\n', '<br/>')
                # Échapper les caractères HTML spéciaux et convertir en paragraphe
                story.append(Paragraph(para_html, body_style))
                story.append(Spacer(1, 0.3 * cm))

        # Générer le PDF
        try:
            doc.build(story)
            buffer.seek(0)
            return buffer
        except Exception as e:
            raise Exception(f"Erreur lors de la génération du PDF : {str(e)}")
