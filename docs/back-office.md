# Back-office JobPilot-AI

Interface d'administration métier, accessible sur `/administration/`.
Elle complète l'admin Django natif (`/admin/`), qui reste disponible pour les
opérations bas niveau sur la base.

## Accès

| Rôle | Accès |
|---|---|
| Visiteur non connecté | redirigé vers la page de connexion |
| Candidat connecté | **403** (les tentatives sont loggées) |
| `is_staff` | tous les volets sauf *Paramètres* |
| `is_superuser` | tout, y compris *Paramètres* |

Créer un accès :

```bash
python manage.py createsuperuser
# ou, pour un accès en lecture/assistance sans droit sur les réglages :
python manage.py shell -c "from users.models import CustomUser; \
    CustomUser.objects.filter(email='x@y.z').update(is_staff=True)"
```

## Les volets

| Volet | URL | Contenu |
|---|---|---|
| Vue d'ensemble | `/administration/` | inscriptions (24 h / 7 j / 30 j), abonnés, revenus, courbe sur 30 jours, entonnoir d'activation, derniers inscrits, échéances |
| Utilisateurs | `/administration/utilisateurs/` | recherche, filtres, tri, fiche détaillée, actions d'assistance, export CSV |
| Revenus | `/administration/revenus/` | encaissements Stripe, MRR estimé, panier moyen, ARPU, transactions |
| Offres & matching | `/administration/contenu/` | CV analysés, offres France Travail, qualité du matching, état des alertes |
| Paramètres | `/administration/parametres/` | réglages généraux + état des variables d'environnement |
| Supervision | `/administration/supervision/` | santé des services, tâches planifiées, erreurs applicatives |
| Journal | `/administration/journal/` | audit de toutes les actions admin |

## Paramètres et effets réels

Les réglages ne sont pas décoratifs — chacun agit sur le site :

| Réglage | Effet |
|---|---|
| `maintenance_mode` | `MaintenanceModeMiddleware` renvoie une page 503 aux visiteurs. Le back-office, l'admin Django, les webhooks Stripe et les comptes `is_staff` continuent de passer. |
| `registrations_open` | la vue `register` refuse le GET **et** le POST |
| `signup_free_credits` | solde de crédits attribué à l'inscription |
| `max_resumes_per_user` | plafond appliqué dans `upload_resume` |
| `matching_min_score` | seuil par défaut de `check_new_offers` (surchargé par `--min-score`) |
| `alerts_enabled` | coupe l'envoi des alertes (contournable avec `--force`) |
| `alerts_max_offers_per_email` | plafonne le nombre d'offres retenues par alerte |
| `support_notice` | bandeau bleu affiché en haut du site |

Les réglages sont mis en cache 5 minutes (`SiteSettings.load()`), invalidé à
chaque enregistrement. Attention : avec `LocMemCache`, le cache n'est pas
partagé entre processus — la propagation peut prendre jusqu'à 5 minutes sur un
serveur multi-workers. La supervision le signale.

## Supervision des tâches planifiées

`check_new_offers` et `cleanup_expired_alerts` enregistrent chaque exécution
dans `TaskRun`. La page de supervision compare la dernière exécution réussie à
la fréquence attendue (`administration/services/health.py`, `EXPECTED_TASKS`)
et lève une alerte au-delà.

C'est ce qui rend visible un cron cassé. Exemple de configuration :

```cron
0 */6 * * * cd /chemin/vers/JobPilot && .venv/bin/python manage.py check_new_offers
30 3 * * *  cd /chemin/vers/JobPilot && .venv/bin/python manage.py cleanup_expired_alerts
```

Pour instrumenter une nouvelle commande :

```python
from administration.services.tasks import track_run

with track_run("ma_commande") as run:
    ...
    run.items_processed = n
```

puis l'ajouter à `EXPECTED_TASKS` avec l'intervalle toléré.

## Données personnelles

- La consultation d'une fiche utilisateur est journalisée (`USER_VIEWED`).
- Chaque action d'assistance exige un motif, conservé dans le journal.
- L'export CSV est **anonymisé** : identifiants techniques et agrégats, pas
  d'email ni de nom.
- Les CV ne sont pas téléchargeables depuis le back-office.
- La page Paramètres affiche « configuré / manquant » pour les secrets, jamais
  leur valeur.
- Le journal d'audit est en lecture seule, y compris dans l'admin Django.

## Tests

```bash
python manage.py test administration
```
