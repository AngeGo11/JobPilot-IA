# SEO — état des lieux et procédures

## Ce qui est en place dans le code

| Élément | Emplacement |
| --- | --- |
| `<title>` optimisé | `templates/index.html`, bloc `title` de `templates/base.html` |
| Meta description (152 caractères) | `templates/index.html`, bloc `meta_description` de `base.html` |
| Balise canonical | `base.html` (via `CANONICAL_URL`), en dur sur la home |
| Open Graph + Twitter Card | `base.html` et `index.html` |
| Image de partage 1200×630 | `static/images/og-image.png` |
| Sitemap XML | `JobPilot/sitemaps.py`, exposé sur `/sitemap.xml` |
| robots.txt | `templates/robots.txt`, exposé sur `/robots.txt` |
| Google Analytics 4 | `templates/partials/_analytics.html`, inclus dans `base.html` et `index.html` |
| Données structurées `Organization` + `WebSite` + `SoftwareApplication` | `templates/index.html` (JSON-LD, un seul `@graph`) |
| Témoignages clients (mécanisme) | `administration.models.Testimonial`, section conditionnelle dans `index.html` |
| Tests de non-régression | `tests/test_seo.py`, `tests/test_performance_securite.py` |

Performance front, accessibilité et en-têtes de sécurité : voir
[performance-securite.md](performance-securite.md).

L'URL canonique et le lien `Sitemap:` sont construits à partir de la variable
d'environnement `SITE_URL` : en préproduction, ils suivent automatiquement le
domaine configuré. Le sitemap n'utilise **pas** la table `django_site` (qui
contient encore `example.com`) mais ce même `SITE_URL`.

## Activer Google Analytics 4

1. Créer une propriété GA4 → *Flux de données* → *Web* → récupérer l'identifiant
   de mesure `G-XXXXXXXXXX`.
2. Renseigner `GA_MEASUREMENT_ID=G-XXXXXXXXXX` dans les variables
   d'environnement de production (App Service → Configuration). Laisser vide en
   local : sans valeur, aucun script n'est injecté.
3. Redéployer, puis vérifier dans GA4 → *Temps réel*.

### Consentement (RGPD / CNIL)

Le snippet déclare Consent Mode v2 avec **toutes les catégories refusées par
défaut**. En l'état, GA4 n'écrit aucun cookie : la mesure est modélisée, donc
partielle mais licite sans bandeau. Pour récupérer une mesure complète, il faut
brancher une bannière de consentement (Axeptio, Tarteaucitron, Cookiebot…) qui
appelle :

```js
gtag('consent', 'update', { analytics_storage: 'granted' });
```

À défaut de bannière, Matomo en auto-hébergement avec la configuration exemptée
CNIL reste l'alternative la plus simple juridiquement.

## Soumettre le sitemap à Google Search Console

Étape manuelle, à faire une fois en production (aucun accès automatisable) :

1. https://search.google.com/search-console → *Ajouter une propriété* →
   **Domaine** `jobpilot-ai.fr` (couvre apex + www + http/https).
2. Valider par enregistrement DNS TXT chez le registrar.
3. *Sitemaps* → saisir `sitemap.xml` → **Envoyer**. Statut attendu sous 48 h :
   « Réussite », 7 URLs découvertes.
4. *Inspection d'URL* sur `https://jobpilot-ai.fr/` → **Demander l'indexation**.
5. Contrôler dans *Pages* qu'aucune URL privée (`/dashboard/`, `/matching/`…)
   n'est indexée ; elles sont bloquées par robots.txt.

Vérifications rapides après déploiement :

```bash
curl -s https://jobpilot-ai.fr/robots.txt
curl -s https://jobpilot-ai.fr/sitemap.xml | head -20
```

## Publier des témoignages clients

1. Recueillir l'accord **écrit** de la personne sur la citation exacte, le nom
   affiché et le résultat chiffré.
2. `/admin/` → *Témoignages clients* → ajouter l'entrée, renseigner
   `Preuve d'accord` (date et objet du mail, par exemple), puis cocher *Publié*.
3. La section apparaît alors sur l'accueil. Tant qu'aucune entrée n'est publiée,
   rien ne s'affiche — pas de faux avis en attendant.
4. Une fois plusieurs témoignages en ligne, on pourra ajouter `aggregateRating`
   au JSON-LD : il n'est éligible aux étoiles dans les résultats que si les avis
   sont réellement collectés et visibles sur la page.

## Reste à faire (hors périmètre de ce lot)

- Contenu : la home est la seule page indexable à valeur ajoutée. Des pages
  d'atterrissage par métier / région (« offres d'emploi développeur à Lyon »)
  sont le principal levier de trafic organique.
- `hreflang` inutile tant que le site est monolingue français.
- Performance (Core Web Vitals) : traité, voir
  [performance-securite.md](performance-securite.md).
