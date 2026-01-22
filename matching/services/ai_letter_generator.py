"""
Service pour la génération automatique de lettres de motivation par IA.
"""
import os
from typing import Optional
import google.generativeai as genai




class AILetterGenerator:
    """
    Service responsable de la génération de lettres de motivation
    en utilisant l'API Google Gemini.
    """

    def __init__(self):
        """
        Initialise le service avec la clé API Google Gemini.
        La clé doit être dans les variables d'environnement (GEMINI_API_KEY).
        """
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY n'est pas définie dans les variables d'environnement. "
                "Ajoutez-la dans votre fichier .env"
            )
        genai.configure(api_key=api_key)
        self.client = genai.GenerativeModel('gemini-2.5-flash')

    def generate_cover_letter(
            self,
            resume,
            job_match,
            custom_instructions: Optional[str] = None,
            tone: str = "professional"
    ) -> str:
        """
        Génère une lettre de motivation personnalisée.
        
        Args:
            resume: Instance du modèle Resume (avec extracted_text)
            job_match: Instance du modèle JobMatch (avec job_offer)
            custom_instructions: Instructions personnalisées de l'utilisateur
            tone: Ton de la lettre ('professional', 'enthusiastic', 'formal')
        
        Returns:
            str: Lettre de motivation générée
        
        Raises:
            ValueError: Si les données nécessaires sont manquantes
            Exception: Si l'appel à l'API échoue
        """
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

        # Ajout des instructions personnalisées si fournies
        if custom_instructions:
            prompt += f"\n\nINSTRUCTIONS PERSONNALISÉES :\n{custom_instructions}\n"

        try:
            # Appel à l'API Gemini
            response = self.client.generate_content(prompt)

            # Extraction du texte de la réponse
            if hasattr(response, 'text'):
                cover_letter = response.text.strip()
            elif hasattr(response, 'candidates') and response.candidates:
                cover_letter = response.candidates[0].content.parts[0].text.strip()
            else:
                raise ValueError("Format de réponse inattendu de l'API Gemini")

            return cover_letter

        except Exception as e:
            raise Exception(f"Erreur lors de la génération de la lettre de motivation : {str(e)}")

    def refine_cover_letter(
            self,
            existing_letter: str,
            instructions: str
    ) -> str:
        """
        Améliore ou modifie une lettre de motivation existante.
        
        Args:
            existing_letter: Lettre de motivation actuelle
            instructions: Instructions pour l'amélioration (ex: "Rends-la plus courte", 
                         "Ajoute plus d'enthousiasme", "Corrige les fautes")
        
        Returns:
            str: Lettre améliorée
        
        Raises:
            ValueError: Si la lettre ou les instructions sont vides
            Exception: Si l'appel à l'API échoue
        """
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
            response = self.client.generate_content(prompt)

            if hasattr(response, 'text'):
                refined_letter = response.text.strip()
            elif hasattr(response, 'candidates') and response.candidates:
                refined_letter = response.candidates[0].content.parts[0].text.strip()
            else:
                raise ValueError("Format de réponse inattendu de l'API Gemini")

            return refined_letter

        except Exception as e:
            raise Exception(f"Erreur lors de l'amélioration de la lettre : {str(e)}")
    
    def _build_refinement_instructions(self, custom_instructions: str, improvement_type: str) -> str:
        """
        Construit les instructions d'amélioration finales en combinant le type et les instructions personnalisées.
        
        Args:
            custom_instructions: Instructions personnalisées de l'utilisateur
            improvement_type: Type d'amélioration prédéfini
        
        Returns:
            str: Instructions complètes pour l'amélioration
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

    def validate_api_connection(self) -> bool:
        """
        Vérifie que la connexion à l'API Gemini fonctionne.
        
        Returns:
            bool: True si la connexion est OK
        
        Raises:
            Exception: Si la connexion échoue, avec le message d'erreur
        """
        try:
            # Test simple avec un prompt minimal
            test_prompt = "Réponds simplement 'OK' si tu reçois ce message."
            response = self.client.generate_content(test_prompt)

            # Si on arrive ici sans exception, la connexion fonctionne
            return True

        except Exception as e:
            raise Exception(f"Impossible de se connecter à l'API Gemini : {str(e)}")
