"""
Service IA pour adapter le CV à une offre d'emploi spécifique (CV Optimizer).
Utilise Google Gemini pour analyser CV + offre et retourner des suggestions.
"""
import json
import os
import logging
import re
import google.generativeai as genai
from django.conf import settings


class AIOptimizer:
    """
    Service qui utilise Gemini pour comparer un CV à une offre et proposer :
    - Mots-clés manquants dans le CV mais présents dans l'offre
    - Suggestion de profil/résumé introductif réécrit pour coller à l'offre
    - Suggestions de modifications pour les expériences (mettre en avant des compétences)
    """

    def __init__(self):
        api_key = os.getenv('GEMINI_API_KEY') or getattr(settings, 'GEMINI_API_KEY', None)
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY manquant. "
                "Définissez la variable d'environnement GEMINI_API_KEY ou dans settings.py"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')

    def optimize_for_offer(self, cv_text: str, job_description: str, job_title: str = "") -> dict:
        """
        Analyse le CV par rapport à l'offre et retourne des suggestions d'adaptation.

        Args:
            cv_text: Texte brut du CV
            job_description: Description de l'offre d'emploi
            job_title: Titre du poste (optionnel, pour contexte)

        Returns:
            dict: {
                'missing_keywords': list[str],
                'suggested_summary': str,
                'experience_suggestions': list[dict]  # [{'experience': str, 'suggestion': str}, ...]
            }
        """
        if not cv_text or not cv_text.strip():
            return {
                'missing_keywords': [],
                'suggested_summary': '',
                'experience_suggestions': []
            }
        if not job_description or not job_description.strip():
            return {
                'missing_keywords': [],
                'suggested_summary': '',
                'experience_suggestions': []
            }

        title_context = f" pour le poste : {job_title}" if job_title else ""

        prompt = f"""Tu es un expert en recrutement et en optimisation de CV. Ta mission est d'aider un candidat à adapter son CV à une offre d'emploi précise.

DOCUMENT 1 : CV ACTUEL DU CANDIDAT
---
{cv_text[:6000]}
---

DOCUMENT 2 : OFFRE D'EMPLOI
---
Titre du poste : {job_title or "Non spécifié"}
---
{job_description[:6000]}
---

Analyse les deux documents et retourne UNIQUEMENT un JSON valide (sans texte avant ou après) avec la structure exacte suivante :

{{
  "missing_keywords": ["mot1", "mot2", "..."],
  "suggested_summary": "Texte du résumé ou profil introductif réécrit pour coller à l'offre (2-4 phrases). Met en avant les compétences qui matchent et reformule pour utiliser le vocabulaire de l'offre.",
  "experience_suggestions": [
    {{ "experience": "Titre ou résumé court de l'expérience (ex: Développeur chez X)", "suggestion": "Conseil pour mettre en avant telle compétence ou reformuler pour l'offre" }},
    ...
  ]
}}

RÈGLES :
1. missing_keywords : liste des mots-clés ou compétences importants dans l'offre qui ne figurent pas (ou peu) dans le CV. Maximum 15 éléments, des termes concrets (technologies, soft skills mentionnés dans l'offre).
2. suggested_summary : réécris une accroche / résumé professionnel que le candidat pourrait mettre en tête de son CV pour cette offre. En français, 2-4 phrases percutantes.
3. experience_suggestions : pour 1 à 3 expériences les plus pertinentes du CV, donne une suggestion courte (1-2 phrases) pour les reformuler ou mettre en avant une compétence en lien avec l'offre. Si le CV n'a pas de sections expériences claires, tu peux proposer des suggestions générales (ex: "Mettre en avant votre expérience en Python dans la section X").
4. Réponds UNIQUEMENT avec le JSON, sans markdown (pas de ```json).
"""

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()

            # Nettoyage des blocs markdown
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            elif response_text.startswith('```'):
                response_text = response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            try:
                result = json.loads(response_text)
            except json.JSONDecodeError as e:
                logging.warning(f"Erreur parsing JSON CV Optimizer : {e}. Réponse : {response_text[:500]}")
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    return {
                        'missing_keywords': [],
                        'suggested_summary': '',
                        'experience_suggestions': []
                    }

            missing_keywords = result.get('missing_keywords', [])
            if not isinstance(missing_keywords, list):
                missing_keywords = []
            missing_keywords = [str(k).strip() for k in missing_keywords if k and str(k).strip()][:15]

            suggested_summary = result.get('suggested_summary') or ''
            if not isinstance(suggested_summary, str):
                suggested_summary = str(suggested_summary).strip()

            experience_suggestions = result.get('experience_suggestions', [])
            if not isinstance(experience_suggestions, list):
                experience_suggestions = []
            cleaned_suggestions = []
            for item in experience_suggestions[:5]:
                if isinstance(item, dict) and item.get('experience') and item.get('suggestion'):
                    cleaned_suggestions.append({
                        'experience': str(item['experience']).strip(),
                        'suggestion': str(item['suggestion']).strip()
                    })

            return {
                'missing_keywords': missing_keywords,
                'suggested_summary': suggested_summary,
                'experience_suggestions': cleaned_suggestions
            }

        except Exception as e:
            logging.error(f"Erreur CV Optimizer Gemini : {e}")
            raise Exception(f"Erreur lors de l'analyse d'adaptation du CV : {str(e)}")
