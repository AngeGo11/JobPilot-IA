# Étapes restantes pour un déploiement prêt

Ce document liste ce qu’il reste à faire pour que JobPilot soit **complètement prêt** pour la mise en production, puis comment le tester sur un hébergement gratuit.

---

## 1. Checklist technique (à faire avant / pendant le déploiement)

### 1.1 Sécurité et configuration Django

| Étape | Détail | Statut |
|-------|--------|--------|
| Désactiver le mode debug | Sur l’hébergeur, définir `DEBUG=False` (variable d’environnement). Ne jamais committer `DEBUG=True` pour la prod. | À faire |
| Environnement | Garder `ENVIRONMENT=production` en prod pour activer HTTPS, cookies sécurisés, HSTS. | À faire |
| Variables obligatoires | Vérifier que toutes les variables utilisées en prod sont définies sur l’hébergeur (voir section 2). | À faire |

### 1.2 Fichiers statiques

| Étape | Détail | Statut |
|-------|--------|--------|
| Définir `STATIC_ROOT` | Dans `settings.py`, ajouter par exemple : `STATIC_ROOT = BASE_DIR / 'staticfiles'`. | À faire |
| Lancer collectstatic | Sur le serveur ou dans le script de déploiement : `python manage.py collectstatic --noinput`. | À faire |
| Servir les statiques | Configurer le serveur web (Nginx, Caddy) ou WhiteNoise pour servir les fichiers sous `STATIC_ROOT`. | À faire |

### 1.3 Base de données

| Étape | Détail | Statut |
|-------|--------|--------|
| PostgreSQL en prod | Utiliser une base PostgreSQL fournie par l’hébergeur (ou externe). Renseigner `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`. | À faire |
| Migrations | Après déploiement : `python manage.py migrate`. | À faire |
| Site Django | Vérifier que le site avec `SITE_ID=1` existe (commande `python manage.py create_site` si besoin). | À faire |

### 1.4 Secrets et .env

| Étape | Détail | Statut |
|-------|--------|--------|
| Ne pas committer .env | Le fichier `.env` doit rester dans `.gitignore` et ne jamais être poussé sur le dépôt. | À vérifier |
| Variables sur l’hébergeur | En prod, définir toutes les clés (Django, DB, Stripe, Gemini, France Travail, OAuth, etc.) dans les variables d’environnement de l’hébergeur (pas de fichier .env dans le repo). | À faire |

### 1.5 Stripe (production)

| Étape | Détail | Statut |
|-------|--------|--------|
| URLs de retour | Remplacer `STRIPE_SUCCESS_URL` et `STRIPE_CANCEL_URL` par les URLs du domaine de prod (ex. `https://JobPilot-IA.fr/subscriptions/success/`). | À faire |
| Clés live (quand tu es prêt) | Pour accepter de vrais paiements : utiliser les clés Stripe **live** (`pk_live_...`, `sk_live_...`) et le bon `STRIPE_WEBHOOK_SECRET` live. | Plus tard |
| Webhook | Configurer l’URL de webhook Stripe vers ton domaine de prod (ex. `https://JobPilot-IA.fr/subscriptions/webhook/`). | À faire |

### 1.6 Domaine et DNS

| Étape | Détail | Statut |
|-------|--------|--------|
| Domaine | Si tu utilises un domaine perso (ex. JobPilot-IA.fr), le pointer vers l’IP ou le CNAME fourni par l’hébergeur. | À faire |
| HTTPS | S’appuyer sur le HTTPS de l’hébergeur (Let’s Encrypt) ou configurer un reverse proxy. | À faire |

### 1.7 Optionnel mais recommandé

| Étape | Détail | Statut |
|-------|--------|--------|
| Cache partagé (Redis) | Pour un rate limiting correct avec plusieurs workers : configurer Redis dans `CACHES` et l’utiliser pour le rate limit Gemini. | Optionnel |
| Logs et monitoring | Vérifier que les logs (fichiers ou stdout) sont accessibles sur l’hébergeur pour le debug. | Optionnel |

---

## 2. Liste des variables d’environnement à définir en production

À configurer dans le tableau de bord de l’hébergeur (pas de `.env` dans le repo) :

```bash
# Django
DEBUG=False
ENVIRONMENT=production
DJANGO_SECRET_KEY=<clé_secrète_forte_et_unique>

# Base de données (PostgreSQL fourni par l’hébergeur)
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=...
DB_PORT=5432

# Site
SITE_URL=https://JobPilot-IA.fr

# Rate limiting Gemini
GEMINI_MAX_RPM=1000
GEMINI_FAIR_USE_LIMIT=50

# Gemini
GEMINI_API_KEY=...

# France Travail
ID_CLIENT=...
CLIENT_SECRET=...
API_BASE_URL=...

# Email (SMTP)
DEFAULT_FROM_EMAIL=JobPilot <noreply@...>
SERVER_EMAIL=...
EMAIL_HOST=...
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...

# Stripe (prod : clés live + URLs de prod)
STRIPE_SECRET_KEY=...
STRIPE_PUBLISHABLE_KEY=...
STRIPE_WEBHOOK_SECRET=...
STRIPE_SUCCESS_URL=https://ton-domaine.fr/...
STRIPE_CANCEL_URL=https://ton-domaine.fr/...
STRIPE_PRICE_PASS24H=...
STRIPE_PRICE_SPRINT=...
STRIPE_PRICE_PRO=...
STRIPE_PRICE_PACK=...

# OAuth (Google, GitHub, LinkedIn) – URLs de redirection autorisées à mettre à jour
ID_CLIENT_GOOGLE=...
SECRET_CLIENT_GOOGLE=...
ID_CLIENT_GITHUB=...
SECRET_CLIENT_GITHUB=...
KEY=...   # LinkedIn si utilisé
```

---

## 3. Hébergement gratuit pour tester

Objectif : déployer une première fois pour vérifier qu’il n’y a pas de problème (DB, static files, env vars, Stripe webhook, etc.) avant de viser un hébergement payant ou un domaine définitif.

### Option recommandée : **Render** (gratuit)

- **Pourquoi** : Offre gratuite avec **PostgreSQL** et **service Web** (Django). Très simple pour un premier déploiement.
- **Limites gratuites** :
  - Le service Web s’endort après ~15 min d’inactivité (le premier chargement peut prendre 1–2 min).
  - La base PostgreSQL gratuite est supprimée après 90 jours (tu peux en recréer une ou migrer vers un autre hébergeur).
- **À faire** :
  1. Créer un compte sur [render.com](https://render.com).
  2. Créer une **PostgreSQL** (gratuite).
  3. Créer un **Web Service** (connecter ton repo Git, build : `pip install -r requirements.txt`, start : `gunicorn JobPilot.wsgi` ou équivalent).
  4. Renseigner toutes les variables d’environnement listées en section 2 (avec les URLs Render pour Stripe success/cancel et webhook).
  5. Ajouter `STATIC_ROOT` et, dans le build, lancer `collectstatic` ; configurer WhiteNoise pour servir les statiques (recommandé sur Render).
- **URL** : Tu obtiendras une URL du type `https://ton-app.onrender.com`. Idéal pour tester.

### Alternative : **Railway** (crédit gratuit)

- **Pourquoi** : Très simple, PostgreSQL + déploiement depuis Git, bonne doc.
- **Limites** : Crédit gratuit mensuel (ex. ~5 $), puis payant. Idéal pour un test de quelques jours/semaines.
- **À faire** : [railway.app](https://railway.app) → New Project → PostgreSQL + déployer le repo, puis configurer les variables d’environnement.

### Autre option : **PythonAnywhere** (gratuit)

- **Pourquoi** : Hébergement Python/Django dédié, gratuit avec sous-domaine `*.pythonanywhere.com`.
- **Limites** : Entrée IP restreinte pour la base (ou utiliser leur MySQL/PostgreSQL proposés), moins flexible que Render/Railway pour les workers et le cache.
- Utile si tu préfères un environnement “tout-en-un” Python.

---

## 4. Ordre des étapes suggéré pour le premier déploiement (test)

1. Ajouter `STATIC_ROOT` et WhiteNoise (ou équivalent) dans le projet.
2. Créer un compte sur **Render** (ou Railway) et une base **PostgreSQL**.
3. Connecter le repo Git et créer un **Web Service** Django (commande Gunicorn + collectstatic dans le build).
4. Définir **toutes** les variables d’environnement (section 2), avec `DEBUG=False` et `ENVIRONMENT=production`.
5. Configurer les URLs Stripe (success, cancel, webhook) avec l’URL fournie par Render (ex. `https://ton-app.onrender.com`).
6. Lancer les **migrations** et la commande **create_site** si besoin.
7. Tester : inscription, connexion, upload CV, recherche, génération lettre, Stripe (mode test).
8. Vérifier les logs en cas d’erreur (onglet Logs sur Render).

Une fois ce déploiement de test OK, tu pourras reprendre la checklist du début de ce fichier pour un déploiement “définitif” (domaine perso, Stripe live, etc.).

---

## 5. Résumé

- **Pour être complètement prêt** : suivre la checklist section 1 (sécurité, statiques, DB, secrets, Stripe, domaine).
- **Pour tester sans risque** : déployer d’abord sur **Render** (gratuit) avec une base PostgreSQL et les variables d’environnement, puis corriger les éventuels problèmes avant de viser la prod “réelle”.
