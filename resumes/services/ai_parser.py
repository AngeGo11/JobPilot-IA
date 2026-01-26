"""
Service d'analyse IA pour extraire le titre du poste et les compétences d'un CV.
Utilise Google Gemini pour analyser le texte extrait du PDF.
"""
import json
import os
import google.generativeai as genai
from django.conf import settings


class AIParser:
    """
    Service qui utilise Gemini pour analyser le texte d'un CV et extraire :
    - Le titre du poste visé (job_title) - LE PLUS IMPORTANT
    - Les compétences techniques (skills)
    """
    
    def __init__(self):
        """Initialise l'API Gemini avec la clé API depuis les settings."""
        api_key = os.getenv('GEMINI_API_KEY') or getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY manquant. "
                "Définissez la variable d'environnement GEMINI_API_KEY ou dans settings.py"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
    
    def extract_job_info(self, cv_text):
        """
        Analyse le texte du CV et extrait le titre du poste visé et les compétences.
        
        Args:
            cv_text (str): Texte brut extrait du CV
            
        Returns:
            dict: {
                'job_title': str ou None,
                'skills': list[str] ou []
            }
            
        Raises:
            ValueError: Si le parsing JSON échoue
            Exception: Si l'appel à Gemini échoue
        """
        if not cv_text or not cv_text.strip():
            return {
                'job_title': None,
                'skills': []
            }
        
        # Prompt pour Gemini - demande un JSON strict
        prompt = f"""Analyse ce CV et extrais les informations suivantes au format JSON strict :

1. **job_title** (LE PLUS IMPORTANT) : Le titre du poste que le candidat recherche ou vise. Généralement sur les premières lignes du cv
   Exemples : "Stage Data Engineer", "Alternance Développeur Java", "CDI Développeur Full Stack", "Boulanger", "Stage Marketing Digital"
   Si le CV ne mentionne pas explicitement un poste recherché, essaie de l'inférer à partir du contenu (expériences, formations, compétences).
   Si vraiment impossible à déterminer, retourne null.

2. **skills** : Liste des compétences techniques, langages, outils, frameworks mentionnés dans le CV.
   Exemples : ["Python", "Django", "Docker", "PostgreSQL", "React", "Git"]
   Retourne une liste vide [] si aucune compétence technique n'est détectée.

IMPORTANT : 
- Réponds UNIQUEMENT avec un JSON valide, sans texte avant ou après.
- Format exact attendu : {{"job_title": "...", "skills": [...]}}
- Le job_title est la priorité absolue pour la recherche d'emploi.

Texte du CV :
{cv_text[:4000]}  # Limite à 4000 caractères pour éviter les tokens excessifs
"""
        
        try:
            # Appel à Gemini
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Nettoyage : enlever les markdown code blocks si présents
            if response_text.startswith('```json'):
                response_text = response_text[7:]  # Enlever ```json
            elif response_text.startswith('```'):
                response_text = response_text[3:]  # Enlever ```
            if response_text.endswith('```'):
                response_text = response_text[:-3]  # Enlever ``` à la fin
            
            response_text = response_text.strip()
            
            # Parsing JSON
            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                # Si le JSON est invalide, on essaie d'extraire manuellement
                print(f"⚠️ Erreur parsing JSON : {e}")
                print(f"Réponse brute de Gemini : {response_text}")
                # Fallback : chercher le JSON dans la réponse
                import re
                json_match = re.search(r'\{[^{}]*"job_title"[^{}]*"skills"[^{}]*\}', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    raise ValueError(f"Impossible de parser la réponse JSON de Gemini : {response_text}")
            
            # Validation et normalisation
            job_title = result.get('job_title')
            skills = result.get('skills', [])
            
            # Normalisation
            if job_title and isinstance(job_title, str):
                job_title = job_title.strip()
                if not job_title or job_title.lower() in ['null', 'none', '']:
                    job_title = None
            
            if not isinstance(skills, list):
                skills = []
            # Nettoyer les skills (enlever les doublons, les valeurs vides)
            skills = [s.strip() for s in skills if s and isinstance(s, str) and s.strip()]
            skills = list(set(skills))  # Supprimer les doublons
            
            return {
                'job_title': job_title,
                'skills': skills
            }
            
        except Exception as e:
            print(f"❌ Erreur lors de l'appel à Gemini : {e}")
            raise Exception(f"Erreur lors de l'analyse IA du CV : {str(e)}")
