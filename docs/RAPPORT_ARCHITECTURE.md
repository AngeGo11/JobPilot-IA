# Rapport de mise en œuvre — architecture JobPilot-AI

**Date :** 15 août 2026
**Référence :** [revue d'architecture](https://claude.ai/code/artifact/90b79a6e-c75e-4165-9a77-1a96b6f45711)
**Périmètre retenu :** structure du dépôt + phases 1, 2, 3 et 4 (plan complet)

---

## 1. Résumé

| Indicateur | Avant | Après |
|---|---|---|
| Tests | 58 | **119** |
| Durée de la suite | 344 s | **1 s** |
| `matching/views.py` | 813 lignes | **713 lignes** |
| Matching | Jaccard × 300 | **embeddings + cosinus** |
| Appels IA | dans la requête web | **dans un worker Celery** |
| Réponse web sur action IA | durée complète de l'appel Gemini | **~50 ms** |
| Workers gunicorn | 1 (défaut implicite) | **4** |
| Timeout HTTP | 600 s | **60 s** |
| Cache | LocMem par processus | **Redis partagé** |
| Index composites | 0 | **6** |
| Traçabilité des crédits | aucune | **registre `CreditEntry`** |
| CI | déploie sans tester | **tests bloquants avant déploiement** |
| Fichiers de settings | 1 × 458 lignes | **base / dev / prod / test** |

Toutes les modifications sont vérifiées par la suite de tests. Aucun changement
n'a été appliqué à la production.

---

## 2. Ce qui a été fait

### 2.1 Structure du dépôt

**`.gitignore` réécrit.** Trois problèmes corrigés :

- `docs` excluait **tout** le dossier : schéma de base, UML, générateurs `.docx`
  (746 lignes de Python) et documentation du back-office n'étaient pas versionnés.
  Seuls les `.docx` régénérables restent exclus.
- `./JobPilot/settings.py` ne faisait rien — git rejette les motifs commençant
  par `./`. Ligne supprimée pour ne plus laisser croire à une protection.
- `.idea/` était **versionné** (7 fichiers, dont `workspace.xml` qui change à
  chaque ouverture de l'IDE). Retiré du suivi via `git rm --cached`.

**Réglages éclatés** — `JobPilot/settings.py` devient un paquet :

```
JobPilot/settings/
├── __init__.py   aiguillage automatique selon ENVIRONMENT
├── base.py       commun (ex-settings.py)
├── dev.py        HTTP, stockage local, garde-fou base distante
├── prod.py       HTTPS, HSTS, contrôles au démarrage
└── test.py       cache mémoire, hachage rapide, stockage simple
```

`DJANGO_SETTINGS_MODULE` reste `JobPilot.settings` : **aucune modification
requise côté Azure**. `manage.py test` charge `test.py` automatiquement, ce qui
a permis de supprimer le contournement `plain_static` des tests.

**Lecture d'environnement rendue non fatale.** `os.getenv("DEBUG").lower()`
levait une `AttributeError` si la variable manquait ; `int(os.getenv('GEMINI_MAX_RPM'))`
un `TypeError`. Remplacés par `env_bool()` / `env_int()` avec valeurs par défaut.
`DEBUG` vaut désormais `False` par défaut : une variable oubliée produit un site
sûr, pas un site exposant ses tracebacks.

**Tests unifiés.** Le répertoire racine `test/` (singulier, convention pytest,
sans pytest dans les dépendances) est supprimé :

- `test_francetravail_cache.py` → `matching/tests.py`
- `test_settings_security.py` → `tests/test_settings_security.py`

**Dépendances éclatées et figées** — `requirements/{base,dev,prod}.txt`.
Les versions sont alignées sur ce qui est réellement installé. `requirements.txt`
reste à la racine (Oryx l'attend) et pointe vers `prod.txt`.

> `dotenv==0.9.9` a été retiré : c'est un paquet **distinct** de `python-dotenv`,
> qui est celui réellement utilisé (`from dotenv import load_dotenv`).

**Nouveaux outils de développement :**

| Fichier | Rôle |
|---|---|
| `.env.example` | modèle documenté, versionné |
| `Makefile` | `make services`, `migrer`, `seed`, `serveur`, `worker`, `beat`, `tests` |
| `scripts/dev-env.sh` | charge un environnement local sûr |
| `deploy/Dockerfile` | image réelle (remplace le squelette `ubuntu` + `top -b`) |
| `deploy/deploy.sh` | démarrage gunicorn corrigé |

### 2.2 Phase 1 — disponibilité

**Cache partagé.** `CACHES` n'était pas défini : Django utilisait `LocMemCache`,
local à chaque processus. Trois mécanismes en dépendaient — le compteur RPM
« global » de Gemini, le quota horaire par utilisateur, le token OAuth France
Travail. Avec N workers, la limite « 10 requêtes/minute » devenait 10 × N.
Redis, déjà présent dans `docker-compose.yml` mais branché nulle part, est
maintenant configuré via `REDIS_URL`, avec repli sur LocMem en son absence.
Vérifié en conditions réelles : trois processus Python distincts incrémentant
le compteur RPM aboutissent à `3` — avec LocMem, chacun serait resté à `1`.

**Workers gunicorn.** `deploy.sh` lançait `gunicorn` sans `--workers` : le défaut
est **1 worker synchrone**, soit une requête à la fois pour tout le site. Passé
à 4 (ajustable par `WEB_CONCURRENCY`), et `--timeout` ramené de 600 s à 60 s.

**Six index composites**, sur les requêtes réellement exécutées :

| Modèle | Index | Requête servie |
|---|---|---|
| `JobMatch` | `user, is_unlocked, -score` | dashboard candidat |
| `JobMatch` | `resume, is_unlocked` | écran de résultats d'un CV |
| `JobMatch` | `status, -matched_at` | statistiques back-office |
| `JobOffer` | `-created_at`, `-date_posted` | volumétrie et alertes |
| `Resume` | `user, -uploaded_at` | liste des CV |

**Dockerfile réel** : construction en deux étapes, `collectstatic` à la
construction, utilisateur non privilégié, `HEALTHCHECK`.

**CI qui teste avant de déployer.** `.github/workflows/ci.yml` exécute
`manage.py check`, `makemigrations --check` (détecte un modèle modifié sans
migration), la suite de tests et `check --deploy`. Le workflow de déploiement
existant est conditionné à son succès (`needs: ci`).

### 2.3 Phase 3 — crédits auditables

**Le problème.** Le motif était partout : `consume_credit()` → appel réseau long
→ `refund_credit()` en cas d'échec. Le solde était un simple entier sur
`CustomUser`. Si le processus mourait entre les deux — timeout, redéploiement,
OOM — le remboursement n'avait jamais lieu et **rien n'était écrit nulle part**.

**Le registre.** `subscriptions.CreditEntry` enregistre chaque mouvement
(`delta`, motif, opération, écriture annulée, solde après, date), dans la même
transaction que la mise à jour du solde. Le service
`subscriptions/services/credits.py` expose `debit()`, `refund()`, `grant()`,
`ledger_balance()`, `history()`.

Deux corrections de comportement au passage :

1. **`refund()` prend l'écriture, pas l'utilisateur.** L'ancienne version
   ajoutait aveuglément +1 : elle pouvait créditer un abonné premium jamais
   débité, ou créditer deux fois via deux blocs `except` imbriqués. Un
   remboursement est désormais idempotent par construction.
2. **`grant()` borne le solde à zéro.** Un solde négatif bloquait
   `can_generate` durablement.

**La couche `use_cases`.** `matching/use_cases.py` contient `AIOperation`, qui
enchaîne débit → exécution → remboursement garanti :

```python
try:
    lettre = AIOperation('generate_letter').run(request.user, action)
except InsufficientCredits:
    return JsonResponse({'error': MSG_NO_CREDIT}, status=402)
except AIOperationError as exc:
    return JsonResponse({'error': exc.message}, status=exc.status)
```

Les six branches d'exception (`BrokenPipeError`, `FairUseExceeded`,
`GeminiServiceUnavailable`, `ValueError`, `Exception`) étaient recopiées quatre
fois dans les vues, chacune devant penser à rembourser. Le remboursement est
maintenant **structurel** : il vit dans le `except` de `run()` et aucun chemin
de sortie ne peut le contourner. À ce stade, `matching/views.py` passe de 813 à
664 lignes ; la phase 2 y ajoutera ensuite le point d'entrée de suivi des
traitements, d'où les 713 lignes finales.

**Points d'entrée routés vers le registre :** inscription (`users/views.py`),
achat Stripe (`subscriptions/services/stripe_api.py`), ajustement manuel depuis
le back-office (`administration/views.py`).

**Commande de réconciliation.** `manage.py reconcile_credits` compare, pour
chaque compte, le solde et la somme du registre. Sur la base locale, elle
détecte les 97 comptes antérieurs au registre ; `--fix` leur pose une écriture
d'ouverture. Après quoi tout écart signale une mutation passée à côté du service.

**Back-office.** La fiche utilisateur affiche l'historique complet des
mouvements et un indicateur de cohérence solde / registre.

### 2.4 Phase 2 — sortir l'IA de la requête

**Le problème.** `gemini_safe` fait du backoff par `time.sleep(1, 2, 4)` plus
jusqu'à 3 s d'attente sur le rate limit — jusqu'à 10 s de sommeil pur dans le
thread qui sert la page HTTP, avant même la latence de Gemini. Le
`--timeout 600` d'origine était la cicatrice de ce problème.

**Ce qui a été mis en place :**

| Élément | Rôle |
|---|---|
| `JobPilot/celery.py` | application Celery, découverte des tâches, planification |
| `matching/tasks.py` | 3 tâches facturées + 3 tâches de maintenance |
| `matching.AIJob` | suivi d'un traitement : propriétaire, statut, résultat, erreur |
| `AIOperation.enqueue()` | débite puis confie le travail à un worker |
| `/matching/taches/<task_id>/` | état d'un traitement, réservé à son propriétaire |
| `window.postAIJob()` | interrogation transparente côté navigateur |
| services `worker` et `beat` | dans `docker-compose.yml`, profil `workers` |

**Le contrat de facturation.** Le débit reste **synchrone**, dans la requête
web : l'utilisateur doit apprendre tout de suite qu'il n'a plus de crédits, pas
trente secondes plus tard par un statut d'échec. La tâche reçoit l'identifiant
de l'écriture et se charge elle-même du remboursement si elle échoue, quel que
soit le mode de défaillance.

**Pourquoi un modèle `AIJob` plutôt que le seul identifiant Celery.** Le
navigateur interroge l'état par identifiant de tâche. Sans propriétaire
enregistré, connaître un identifiant suffirait à lire la lettre de motivation
d'un autre candidat. Les identifiants sont des UUID, donc difficiles à deviner
— mais « difficile à deviner » n'est pas un contrôle d'accès. Le modèle donne
en prime la visibilité des traitements dans la supervision du back-office, ce
que le backend de résultats Celery ne conserve que 24 h.

**Compatibilité de l'interface.** `window.postAIJob()` masque la différence
entre une réponse `200` (traitement déjà terminé, environnement sans broker) et
une réponse `202` suivie d'interrogations. La charge utile finale garde les
noms attendus par le JavaScript existant (`refined_letter`, `data`,
`new_credits`) : aucun gestionnaire de réponse n'a eu à être réécrit.

**Sans broker, rien ne casse.** `CELERY_TASK_ALWAYS_EAGER` s'active
automatiquement quand `CELERY_BROKER_URL` est absente : les tâches s'exécutent
alors en direct, comme avant. C'est aussi le mode utilisé par la suite de tests.

**Planification versionnée.** `check_new_offers` et `cleanup_expired_alerts`
deviennent des tâches Celery Beat déclarées dans `JobPilot/celery.py`. Plus de
ligne de cron à configurer à la main sur l'hébergeur, et `TaskRun` reste
alimenté pour la page de supervision. Une tâche `purge_finished_jobs` supprime
les traitements terminés depuis plus de 7 jours.

**Vérification de bout en bout**, avec un vrai worker branché sur Redis :

```
  web rendu en          : 49 ms
  statut immédiat       : pending
  solde après débit     : 2
  statut après worker   : failure
  solde après worker    : 3  (remboursé)
  registre reconstitué  : 3
```

La requête web rend la main en 49 ms là où elle attendait auparavant toute la
durée de l'appel Gemini. Le crédit débité à l'enfilement a bien été rendu par
le worker, et le registre reconstitué concorde avec le solde.

### 2.5 Phase 4 — matching sémantique

**Le problème, mesuré.** `calculate_match_score()` compare deux sacs de mots.
Sur un CV de développeur backend Python/Django confronté à deux offres réelles :

| Offre | Mots-clés | Sémantique |
|---|---|---|
| Ingénieur logiciel Flask/FastAPI — *même métier, vocabulaire différent* | **0 %** | 90 % |
| Commercial B2B — *autre métier, vocabulaire d'entreprise commun* | **71 %** | 47 % |

Le score par mots-clés rate complètement l'offre pertinente et retient l'offre
hors sujet **au-dessus du seuil d'alerte de 70 %**. Concrètement : le candidat
reçoit un email pour le poste de commercial et n'entend jamais parler du poste
d'ingénieur.

**Ce qui a été mis en place :**

| Élément | Rôle |
|---|---|
| `pgvector` | extension PostgreSQL, colonnes `vector(768)`, index HNSW |
| `matching/services/embeddings.py` | vectorisation via `gemini-embedding-001` |
| `matching/services/scoring.py` | similarité cosinus, bascule, repli |
| `JobMatch.semantic_score` | second score, calculé en parallèle |
| `SiteSettings.semantic_matching_enabled` | interrupteur de bascule |
| `backfill_embeddings` | rattrapage du contenu existant |
| Panneau de comparaison | dans « Offres & matching » du back-office |

**Le mode ombre.** Le score sémantique est calculé et stocké, mais
`display_score` continue de renvoyer le score par mots-clés tant que
l'interrupteur est décoché. On accumule de quoi comparer les deux méthodes sur
du contenu réel avant de basculer, plutôt que de changer d'algorithme sur une
intuition. Un repli automatique couvre les offres tout juste ingérées, pas
encore vectorisées.

**Deux erreurs corrigées grâce à la vérification contre l'API réelle :**

1. **Le modèle n'existait pas.** J'avais écrit `text-embedding-004` de mémoire ;
   l'API répond `404`. Le modèle exposé est `gemini-embedding-001`
   (3072 dimensions par défaut, ramené à 768 via `output_dimensionality`).
2. **La calibration était fausse.** J'avais supposé une plage de similarité
   [0,30 ; 0,90]. Mesurée, elle vaut **[0,727 ; 1,000]** : deux annonces
   d'emploi françaises partagent registre et tournures quel que soit le métier.
   Avec ma calibration initiale, un CV de développeur face à une offre de
   boulanger obtenait **71 %** — au-dessus du seuil d'alerte. Après
   recalibration sur les mesures :

   | Cas | Cosinus | Score |
   |---|---|---|
   | texte identique | 1,000 | 100 % |
   | même métier, mots différents | 0,864 | 90 % |
   | métier proche | 0,845 | 78 % |
   | commercial (vocabulaire commun) | 0,795 | 47 % |
   | autre métier technique | 0,752 | 20 % |
   | métier sans rapport | 0,727 | 5 % |

   Ces bornes sont des constantes documentées (`SIMILARITY_FLOOR`,
   `SIMILARITY_CEILING`) et verrouillées par un test. **Elles dépendent du
   modèle** : à remesurer si `EMBEDDING_MODEL` change.

**Effet de bord utile.** En diagnostiquant le `404`, il est apparu que
`call_gemini_with_retry` traitait toute erreur comme transitoire : un nom de
modèle erroné consommait trois tentatives avec backoff avant d'être signalé
comme « serveurs surchargés ». Les erreurs permanentes (400, 401, 403, 404)
lèvent désormais `GeminiConfigurationError` sans réessai.

**Coût.** Un appel d'embedding par CV et par offre, puis plus rien tant que le
contenu ne change pas (empreinte SHA-256 stockée à côté du vecteur). Ces appels
partagent le quota Gemini avec les générations de lettres :
`backfill_embeddings --dry-run` chiffre le rattrapage avant de le lancer.

> Le panneau de comparaison affiche aujourd'hui des chiffres calculés sur le
> **jeu de démonstration**, dont les descriptions d'offres sont des mots tirés
> au hasard. Ils ne valent rien comme preuve : seule la comparaison sur des
> offres France Travail réelles permettra de décider la bascule.

### 2.6 Sécurité du poste de développement

Découvert en cours de route : le `.env` du projet contient le `DATABASE_URL` de
**production**. Le serveur local et les migrations s'appliquaient donc aux
données réelles.

- `settings/dev.py` **refuse de démarrer** sur un hôte de base distant
  (contournable par `ALLOW_REMOTE_DB=true` pour une lecture ponctuelle).
- `settings/dev.py` force le stockage des médias en local : un `.env` contenant
  `AZURE_ACCOUNT_NAME` faisait écrire les CV de test dans le conteneur Blob de
  production.
- `manage.py seed_demo` refuse de s'exécuter sur une base non locale et crée un
  jeu de données réaliste (129 comptes, 83 CV, 419 matchs, entonnoir et courbes
  d'inscription cohérents).

---

## 3. Ce qui n'a pas été fait

| Élément | Raison |
|---|---|
| **Bascule du matching sémantique** | Le code est en place et tourne en mode ombre. La bascule est une **décision produit**, à prendre après comparaison sur des offres réelles — pas un travail de développement. |
| **Vectorisation complète du contenu existant** | `backfill_embeddings` doit être lancé en production : 238 offres et 83 CV sans vecteur sur la base de démonstration, davantage en production. |
| **Solde dérivé du registre** | Le document cible annonçait « le solde devient une somme ». J'ai retenu une étape intermédiaire plus sûre : **double écriture** (`ai_credits` reste le solde rapide, le registre en est l'historique), plus une commande de réconciliation. Basculer les lectures sur la somme demanderait de toucher chaque gabarit et chaque vue ; c'est faisable une fois le registre stabilisé et réconcilié. |
| **Regroupement sous `apps/`** | Écarté volontairement : casse tous les imports pour un gain de lisibilité racine, alors que la commande de démarrage Azure référence `JobPilot.wsgi`. |
| **`dashboard` fusionné, `utils/` → `core/`** | Cosmétique, sans effet sur les constats. À faire au prochain passage sur ces fichiers. |

---

## 4. Points en attente d'une décision

### 4.1 Secrets à faire tourner

Le fichier `config_azure` (non versionné, mais présent sur le disque) contient
en clair :

- le mot de passe administrateur PostgreSQL de production — le même que dans `.env` ;
- une clé de compte de stockage Azure ;
- un superutilisateur `admin@jobpilot.com` dont le mot de passe trivial, lisible
  dans ce fichier, a été vérifié comme **fonctionnel en production**.

Ces valeurs ont été affichées pendant la session de travail. Trois actions :

1. Changer le mot de passe du superutilisateur `admin@jobpilot.com`, ou désactiver le compte.
2. Faire tourner le mot de passe PostgreSQL et la clé de stockage Azure.
3. Déplacer ces secrets vers les variables d'application Azure et supprimer le fichier.

### 4.2 Migration appliquée en production

Au début de la session, avant d'avoir identifié que le `.env` pointait sur la
production, la migration `administration.0001_initial` y a été appliquée. Elle
**ajoute trois tables neuves** (`sitesettings`, `adminauditlog`, `taskrun`) et
ne modifie ni ne supprime rien d'existant — aucune donnée n'est affectée.

Les migrations produites depuis **ne sont pas appliquées** en production :

- `matching/0008` — index composites
- `matching/0009` — table `AIJob`
- `resumes/0005` — index composites
- `subscriptions/0003` — table `CreditEntry`

Elles s'appliqueront au prochain déploiement via `deploy/deploy.sh`. Prévoir
`manage.py reconcile_credits --fix` juste après, pour poser les soldes
d'ouverture des comptes existants.

### 4.3 `.env` local

Deux pièges corrigés pendant la session :

- `ENVIRONMENT=production` figurait dans le `.env` d'une machine de
  développement. Le module `prod.py` s'y chargeait donc, sans le garde-fou de
  `dev.py`. Il refuse désormais de démarrer si la base est distante et que la
  variable `WEBSITE_INSTANCE_ID` d'Azure App Service est absente — signal fiable
  qu'on n'est pas sur l'hébergeur.
- L'aiguillage des réglages lisait `ENVIRONMENT` **avant** le chargement du
  `.env` : la valeur du fichier était silencieusement ignorée et `dev.py`
  gagnait toujours en local. Le `.env` est maintenant chargé en premier.


Tant que `DATABASE_URL` y pointe sur Azure, tout usage local passe par
`scripts/dev-env.sh` ou `make`. Le plus propre reste de mettre la base locale
dans `.env` et de laisser la production dans les variables Azure uniquement.

---

### 4.4 Infrastructure à provisionner pour la phase 2

Les workers ne servent à rien sans broker. Avant de déployer :

1. **Un Redis accessible en production** (Azure Cache for Redis, ou conteneur
   dédié), renseigné dans `REDIS_URL` et `CELERY_BROKER_URL`.
2. **Un processus worker séparé du site web.** Azure App Service n'héberge
   qu'un seul processus par application : il faut soit une seconde application
   dont la commande de démarrage est
   `celery -A JobPilot worker --loglevel=info`, soit un Container App. Les
   services `worker` et `beat` de `docker-compose.yml` (profil `workers`)
   servent de référence pour la configuration.
3. **Retirer les lignes de cron** `check_new_offers` et `cleanup_expired_alerts`
   une fois `beat` en service, sinon les alertes partiraient en double.

Tant que ces trois points ne sont pas faits, `CELERY_BROKER_URL` reste vide et
l'application retombe automatiquement sur l'exécution synchrone : le
comportement est celui d'avant la phase 2, sans rien casser.

### 4.5 Extension PostgreSQL à autoriser (phase 4)

Le matching sémantique stocke des colonnes `vector(768)`. L'extension `vector`
doit être disponible côté serveur :

- **en local** : `docker-compose.yml` utilise désormais l'image
  `pgvector/pgvector:pg15`, qui l'embarque ;
- **sur Azure Database for PostgreSQL Flexible Server** : l'extension est
  supportée mais doit être **ajoutée au paramètre serveur `azure.extensions`**
  avant la migration, sinon `CREATE EXTENSION vector` échoue et le déploiement
  s'interrompt.

C'est le seul prérequis d'infrastructure de la phase 4 : aucun service
supplémentaire, les vecteurs vivent dans la base existante.

## 5. Environnement de travail en place

```bash
make services     # PostgreSQL (avec pgvector) + Redis en conteneur
make migrer       # migrations sur la base locale
make seed         # jeu de démonstration
make serveur      # http://127.0.0.1:8000
make worker       # worker Celery (traitements IA)
make beat         # planificateur (alertes, purges)
make tests        # 119 tests, ~1 s
```

Sans `make worker`, l'application fonctionne toujours : les traitements
s'exécutent alors dans la requête, comme avant la phase 2.

Back-office de démonstration : `admin@demo.jobpilot.local` / `demo`.

---

## 6. État du schéma cible

| Bloc du schéma | État |
|---|---|
| Web · gunicorn, 4 workers | fait |
| Redis — cache partagé, rate limit réel | fait |
| Redis — file de tâches | fait |
| Workers Celery — retries, timeout par tâche | fait |
| Statut de la tâche → navigateur | fait |
| PostgreSQL — registre de crédits | fait |
| « le solde devient une somme » | **partiel** — double écriture, voir section 3 |
| Matching sémantique (phase 4) | fait, en mode ombre |

## 7. Prochaines étapes

Le plan d'origine est entièrement mis en œuvre. Ce qui reste relève de
l'exploitation et de la décision produit, pas du développement.

**1. Faire tourner les secrets** (section 4.1) — le plus urgent, indépendant de
tout le reste.

**2. Déployer.** Appliquer les migrations, puis dans l'ordre :

```bash
python manage.py reconcile_credits --fix     # soldes d'ouverture
python manage.py backfill_embeddings --dry-run   # chiffrer le coût
python manage.py backfill_embeddings             # vectoriser
```

Prérequis d'infrastructure : Redis et un worker (section 4.4), et l'extension
`vector` autorisée côté Azure (section 4.5).

**3. Décider la bascule du matching.** Laisser le mode ombre tourner quelques
semaines sur des offres réelles, puis regarder dans « Offres & matching » :

- les **faux positifs évités** — offres que les mots-clés retiennent et que le
  sens écarte : c'est le bruit envoyé par email aujourd'hui ;
- les **offres rattrapées** — pertinentes mais ratées par les mots-clés ;
- l'échantillon des plus gros désaccords, à juger à l'œil.

Si le sémantique a visiblement raison sur ces cas, cocher « Matching sémantique
actif » dans les paramètres. Le retour arrière est immédiat : décocher suffit.

**4. Mesurer l'effet.** Le taux de déblocage et le taux de candidature, déjà
suivis dans le back-office, sont les deux indicateurs qui diront si la bascule
a amélioré la pertinence perçue.
