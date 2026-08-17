import os
import requests
from django.conf import settings
from django.core.cache import cache
import logging
from django.db import IntegrityError
from ..models import JobOffer, JobMatch
import re
from django.utils.dateparse import parse_datetime

HTTP_TIMEOUT = 30  # secondes
TOKEN_CACHE_KEY = "francetravail_access_token"


class FranceTravail:

    def __init__(self):
        self.client_id = settings.CLIENT_ID
        self.client_secret = settings.CLIENT_SECRET_KEY
        self.api_url = settings.API_URL
        self.token = None


    def get_access_token(self, client_id, client_secret):
        """
        Récupère le token OAuth2 nécessaire pour interroger l'API.
        Le token est mis en cache jusqu'à son expiration pour éviter
        une requête d'authentification à chaque appel.
        """
        cached_token = cache.get(TOKEN_CACHE_KEY)
        if cached_token:
            return cached_token

        url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"

        # Le scope est crucial pour définir à quelle API on veut accéder
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "api_offresdemploiv2 o2dsoffre",
            "realm": "/partenaire"
        }

        response = requests.post(url, data=payload, headers=headers, timeout=HTTP_TIMEOUT)

        if response.status_code == 200:
            logging.info("✅ Authentification réussie !")
            token_data = response.json()
            access_token = token_data['access_token']
            try:
                expires_in = int(token_data.get('expires_in', 1500))
            except (TypeError, ValueError):
                expires_in = 1500
            # On garde une marge de sécurité de 60s avant l'expiration réelle
            cache.set(TOKEN_CACHE_KEY, access_token, timeout=max(expires_in - 60, 60))
            return access_token
        else:
            logging.info(f"❌ Erreur Auth : {response.status_code}")
            logging.info(response.text)
            return None

    def search_jobs(self, keywords, page: int =1, limit: int = 10):

        # 1. Calcul des bornes (Pagination)
        start_index = (page - 1) * limit
        end_index = start_index + limit - 1

        """Cherche des jobs basés sur une liste de mots-clés"""
        token = self.get_access_token(self.client_id, self.client_secret)

        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json'
        }

        # On combine les compétences (ex: "Python Django")
        # Si keywords est une liste, on joint par des espaces
        if isinstance(keywords, list):
            q = " ".join(keywords)
        else:
            q = keywords

        params = {
            'motsCles': q,
            'range': f"{start_index}-{end_index}",
            'sort': 1  # 1 = Pertinence
        }

        logging.info(f"🔍 Recherche France Travail avec : {q}")

        response = requests.get(self.api_url, headers=headers, params=params, timeout=HTTP_TIMEOUT)

        if response.status_code == 200 or response.status_code == 206:
            return response.json().get('resultats', [])
        elif response.status_code == 204:  # Pas de résultats
            return []
        else:
            logging.info(f"Erreur API : {response.status_code} - {response.text}")
            return []





    def save_jobs(self, jobs_data, user, resume):
        """
        Prend une liste d'offres (JSON) et les sauvegarde en BDD.
        Crée aussi le lien 'Match' avec l'utilisateur.
        """
        saved_matches = []
        new_offer_ids = []

        for job_data in jobs_data:
            # 1. On crée ou récupère l'offre (pour éviter les doublons)
            # Récupérer l'URL de manière sécurisée
            url_origine = job_data.get('origineOffre', {})
            if isinstance(url_origine, dict):
                url = url_origine.get('urlOrigine', '')
            else:
                url = ''
            
            # S'assurer que l'ID existe
            remote_id = str(job_data.get('id', ''))
            if not remote_id:
                logging.info(f"⚠️ Offre ignorée : pas d'ID")
                continue
                
            offer, created = JobOffer.objects.get_or_create(
                remote_id=remote_id,
                defaults={
                    'title': job_data.get('intitule', 'Titre non disponible'),
                    'company_name': job_data.get('entreprise', {}).get('nom', 'Non spécifié') if isinstance(job_data.get('entreprise'), dict) else 'Non spécifié',
                    'description': job_data.get('description', ''),
                    'url': url,
                    'location': job_data.get('lieuTravail', {}).get('libelle', '') if isinstance(job_data.get('lieuTravail'), dict) else '',
                    'contract_type': job_data.get('typeContrat', ''),
                    'date_posted': parse_datetime(job_data.get('dateCreation')) if job_data.get('dateCreation') else None,
                    'raw_api_data': job_data
                }
            )

            # 2. Calcul du score de matching
            description_offre = job_data.get('description', '')
            score = self.calculate_match_score(resume.extracted_text, description_offre)

            # 3. On crée le Match pour ce CV spécifique (s'il n'existe pas déjà)
            # unique_together = ('resume', 'job_offer') permet d'avoir plusieurs matches pour la même offre avec des CVs différents
            match, match_created = JobMatch.objects.get_or_create(
                resume=resume,  # Critère principal : un CV ne peut avoir qu'un match par offre
                job_offer=offer,
                defaults={
                    'user': user,  # Assigné à la création
                    'score': score,
                    'status': 'new'
                }
            )

            # Si le match existait déjà, on met à jour le score au cas où l'algo a changé
            if not match_created:
                match.score = score
                # S'assurer que l'utilisateur est bien assigné (au cas où le match existait sans user)
                if not match.user:
                    match.user = user
                match.save()

            saved_matches.append(match)
            if created:
                new_offer_ids.append(offer.pk)
            logging.info(f"  ✓ Offre sauvegardée: {offer.title} (Score: {score}%)")

        # Vectorisation des offres nouvelles, en tâche de fond : l'appel
        # d'embedding ne doit pas rallonger la recherche que le candidat attend.
        if new_offer_ids:
            try:
                from matching.tasks import embed_offers_task, rescore_resume_matches_task

                embed_offers_task.delay(offer_ids=new_offer_ids)
                rescore_resume_matches_task.delay(resume.pk)
            except Exception:
                # Broker absent : le rattrapage planifié s'en chargera.
                logging.warning("Vectorisation différée : file de tâches indisponible.")

        return saved_matches






    def calculate_match_score(self, resume_text, job_description):
        """
        Compare le texte du CV et la description du job pour calculer un score (0-100).
        Algorithme simple : Présence de mots-clés communs.
        """
        if not resume_text or not job_description:
            return 0

        # 1. Nettoyage basique (minuscules, set de mots uniques)
        resume_words = set(re.findall(r'\w+', resume_text.lower()))
        job_words = set(re.findall(r'\w+', job_description.lower()))

        # 2. On filtre les "stopwords" (le, la, de, et...) qui font du bruit
        stopwords = {'le', 'la', 'les', 'de', 'du', 'des', 'et', 'en', 'un', 'une', 'pour', 'avec', 'nous', 'vous'}
        resume_words = resume_words - stopwords
        job_words = job_words - stopwords

        # 3. Calcul de l'intersection (mots communs)
        common_words = resume_words.intersection(job_words)

        # 4. Score de Jaccard (Intersection / Union)
        # C'est une mesure statistique classique de similarité
        if not job_words:
            return 0

        # On pondère un peu pour que ça soit lisible (x300 c'est arbitraire pour avoir un % sympa)
        # L'idée est : si j'ai 10% des mots en commun, c'est déjà un bon match contextuel
        score = (len(common_words) / len(job_words)) * 300

        return min(int(score), 100)  # On plafonne à 100%


