#  JobPilot AI

**JobPilot AI** est une plateforme intelligente de recherche d'emploi qui analyse votre CV, trouve automatiquement les offres d'emploi pertinentes et aide à la création et personnalisation de lettre de motivations .

##  Table des matières

- [Fonctionnalités](#-fonctionnalités)
- [Technologies utilisées](#-technologies-utilisées)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Utilisation](#-utilisation)
- [Structure du projet](#-structure-du-projet)
- [API et Services externes](#-api-et-services-externes)
- [Développement](#-développement)

##  Fonctionnalités

###  Recherche intelligente d'emploi
- **Analyse automatique du CV** : Extraction des compétences et informations depuis un PDF
- **Matching intelligent** : Calcul de score de pertinence entre votre profil et les offres d'emploi
- **Intégration France Travail** : Synchronisation automatique avec l'API officielle de France Travail
- **Pagination** : Affichage optimisé des résultats avec pagination

### ✍ Génération de lettres de motivation par IA
- **Génération automatique** : Création de lettres de motivation personnalisées avec Google Gemini
- **Amélioration intelligente** : Raffinement de vos lettres existantes selon vos instructions
- **Éditeur WYSIWYG** : Édition avec TinyMCE (toolbar masquée par défaut pour une expérience "distraction-free")
- **Plusieurs tons** : Professionnel, enthousiaste, formel

###  Dashboard de candidatures
- **Vue d'ensemble** : Suivi de toutes vos candidatures en un seul endroit
- **Statistiques** : Total, nouveaux, vus, postulés
- **Workspace de candidature** : Interface split-screen pour consulter l'offre et rédiger la lettre
- **Gestion des statuts** : Nouveau, vu, postulé, rejeté

###  Gestion de compte
- **Authentification sécurisée** : Inscription, connexion, réinitialisation de mot de passe
- **Gestion des CVs** : Upload multiple, CV principal, liste des CVs
- **Profil utilisateur** : Informations personnelles et préférences

##  Technologies utilisées

### Backend
- **Django 5.2.10** : Framework web Python
- **PostgreSQL** : Base de données relationnelle
- **Python 3.11+** : Langage de programmation

### Frontend
- **Tailwind CSS** : Framework CSS utility-first
- **Font Awesome 6.4.0** : Bibliothèque d'icônes
- **TinyMCE 8** : Éditeur WYSIWYG pour les lettres de motivation
- **Inter Font** : Police de caractères moderne

### Services externes
- **Google Gemini AI** : Génération de lettres de motivation
- **France Travail API** : Récupération des offres d'emploi
- **pdfplumber** : Extraction de texte depuis les PDFs

### Outils
- **Docker & Docker Compose** : Containerisation
- **python-dotenv** : Gestion des variables d'environnement

##  Installation

### Prérequis
- Python 3.11 ou supérieur
- PostgreSQL 15 ou supérieur
- Docker et Docker Compose (optionnel, pour la base de données)
- Git

### Étapes d'installation

1. **Cloner le dépôt**
```bash
git clone <url-du-repo>
cd JobPilot
```

2. **Créer un environnement virtuel**
```bash
python -m venv venv
source venv/bin/activate  # Sur Windows: venv\Scripts\activate
```

3. **Installer les dépendances**
```bash
pip install -r requirements.txt
```

4. **Configurer la base de données**

   **Option A : Avec Docker (recommandé)**
   ```bash
   docker-compose up -d db
   ```

   **Option B : PostgreSQL local**
   - Créer une base de données PostgreSQL
   - Configurer les paramètres dans `.env` (voir section Configuration)

5. **Créer le fichier `.env`**
```bash
cp .env.example .env  # Si vous avez un fichier exemple
# Sinon, créez un fichier .env avec les variables nécessaires
```

6. **Appliquer les migrations**
```bash
python manage.py makemigrations
python manage.py migrate
```

7. **Créer un superutilisateur (optionnel)**
```bash
python manage.py createsuperuser
```

8. **Lancer le serveur de développement**
```bash
python manage.py runserver
```

L'application sera accessible sur `http://127.0.0.1:8000/`

## ⚙ Configuration

### Variables d'environnement (.env)

Créez un fichier `.env` à la racine du projet avec les variables suivantes :

```env
# Base de données PostgreSQL
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=...
DB_PORT=...

# France Travail API
ID_CLIENT=votre_client_id
CLIENT_SECRET=votre_client_secret
API_BASE_URL=https://api.francetravail.fr/...

# Google Gemini AI
GEMINI_API_KEY=votre_cle_api_gemini

# Django (Production)
SECRET_KEY=votre_secret_key_django
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Configuration TinyMCE

Pour utiliser TinyMCE avec votre clé API :

1. Inscrivez-vous sur [TinyMCE Cloud](https://www.tiny.cloud/)
2. Obtenez votre clé API
3. Enregistrez vos domaines dans le portail TinyMCE (localhost, 127.0.0.1, etc.)
4. Mettez à jour la clé API dans `templates/dashboard/detail.html`

##  Utilisation

### 1. Inscription et connexion
- Accédez à `/users/register/` pour créer un compte
- Connectez-vous via `/users/login/`

### 2. Uploader un CV
- Allez dans "Mes CVs" (`/resumes/`)
- Uploadez un CV au format PDF
- Le système extrait automatiquement les compétences

### 3. Rechercher des offres
- Depuis la liste de vos CVs, cliquez sur "Rechercher des offres"
- Le système recherche automatiquement sur France Travail
- Les résultats sont affichés avec un score de pertinence

### 4. Générer une lettre de motivation
- Ouvrez le workspace d'une candidature
- Utilisez les boutons IA pour :
  - **Améliorer avec l'IA** : Améliore votre texte existant
  - **Rendre plus formel** : Adapte le ton
- Ou rédigez directement dans l'éditeur TinyMCE

### 5. Gérer vos candidatures
- Consultez votre dashboard (`/dashboard/`)
- Suivez l'état de vos candidatures
- Marquez-les comme "Postulé" une fois envoyées

##  Structure du projet

```
JobPilot/
├── JobPilot/              # Configuration Django principale
│   ├── settings.py        # Paramètres de l'application
│   ├── urls.py            # URLs principales
│   └── wsgi.py            # Configuration WSGI
│
├── users/                 # Application utilisateurs
│   ├── models.py          # CustomUser, CandidateProfile
│   ├── views.py           # Inscription, connexion
│   ├── forms.py           # Formulaires d'authentification
│   └── urls.py            # Routes utilisateurs
│
├── resumes/               # Application CVs
│   ├── models.py          # Modèle Resume
│   ├── views.py           # Upload, liste des CVs
│   ├── services/
│   │   └── pdf_parser.py  # Extraction de texte et compétences
│   └── urls.py
│
├── matching/              # Application matching
│   ├── models.py          # JobOffer, JobMatch
│   ├── views.py           # Recherche, génération lettres
│   ├── services/
│   │   ├── francetravail.py    # Intégration API France Travail
│   │   └── ai_letter_generator.py  # Génération IA
│   ├── forms.py           # Formulaires lettres de motivation
│   └── urls.py
│
├── dashboard/             # Application dashboard
│   ├── views.py           # Vue d'ensemble, workspace
│   └── urls.py
│
├── templates/             # Templates HTML
│   ├── base.html          # Template de base
│   ├── users/             # Pages authentification
│   ├── resumes/           # Pages CVs
│   ├── matching/          # Pages matching
│   └── dashboard/         # Pages dashboard
│
├── media/                 # Fichiers uploadés (CVs)
├── requirements.txt       # Dépendances Python
├── docker-compose.yml     # Configuration Docker
└── README.md              # Ce fichier
```

##  API et Services externes

### France Travail API
- **Authentification** : OAuth2 avec client credentials
- **Endpoint** : API officielle de France Travail
- **Fonctionnalités** : Recherche d'offres par mots-clés, récupération des détails

### Google Gemini AI
- **Modèle** : Gemini 2.0 Flash
- **Utilisation** : Génération et amélioration de lettres de motivation
- **Configuration** : Clé API requise dans `.env`

### TinyMCE Cloud
- **Version** : TinyMCE 8
- **Fonctionnalités** : Éditeur WYSIWYG avec plugins premium (trial)
- **Configuration** : Clé API et domaine enregistré requis

##  Développement

### Commandes utiles

```bash
# Créer une migration
python manage.py makemigrations

# Appliquer les migrations
python manage.py migrate

# Créer un superutilisateur
python manage.py createsuperuser

# Lancer le serveur de développement
python manage.py runserver

# Accéder au shell Django
python manage.py shell

# Collecter les fichiers statiques (production)
python manage.py collectstatic
```

### Tests

```bash
# Lancer les tests
python manage.py test
```

### Docker

```bash
# Démarrer les services (PostgreSQL, Redis, Adminer)
docker-compose up -d

# Arrêter les services
docker-compose down

# Voir les logs
docker-compose logs -f

# Accéder à Adminer (interface DB)
# http://localhost:8080
```

##  Notes importantes

- **Mode DEBUG** : Actuellement activé pour le développement. Désactivez-le en production.
- **SECRET_KEY** : Changez la clé secrète Django en production.
- **Base de données** : Utilisez PostgreSQL en production (SQLite uniquement pour le développement).
- **Fichiers médias** : Les CVs sont stockés dans `media/cvs/`. Configurez un service de stockage en production.

##  Dépannage

### Problème de connexion à la base de données
- Vérifiez que PostgreSQL est démarré
- Vérifiez les variables d'environnement dans `.env`
- Vérifiez que le port n'est pas déjà utilisé

### Erreur API France Travail
- Vérifiez vos identifiants (`ID_CLIENT`, `CLIENT_SECRET`)
- Vérifiez que l'URL de l'API est correcte
- Consultez les logs dans la console

### TinyMCE ne fonctionne pas
- Vérifiez que votre domaine est enregistré dans le portail TinyMCE
- Vérifiez votre clé API
- En développement, utilisez `no-api-key` temporairement

##  Licence

Ce projet est un projet personnel/éducatif.

##  Auteur

**Axel Gomez**
- Email: axelangegomez2004@gmail.com

##  Remerciements

- France Travail pour l'API d'offres d'emploi
- Google pour Gemini AI
- TinyMCE pour l'éditeur WYSIWYG
- La communauté Django

---

**JobPilot** - Votre copilote de carrière intelligent ✈️
