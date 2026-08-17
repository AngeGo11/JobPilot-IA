# Performance front, accessibilité et en-têtes de sécurité

## 1. Chaîne d'assets : tout est auto-hébergé

Avant, chaque page chargeait quatre ressources tierces bloquantes : le compilateur
Tailwind (CDN, ~400 Ko de JavaScript qui génère la CSS **dans le navigateur**),
Font Awesome complet chez cdnjs, un `@import` Google Fonts imbriqué dans un
`<style>` (donc sérialisé après le CSS), et le logo PNG de 2 Mo.

Aujourd'hui :

| Ressource | Avant | Après |
| --- | --- | --- |
| CSS | CDN Tailwind, ~400 Ko de JS + compilation au chargement | `static/css/app.css`, 53 Ko compilés, ~9 Ko en brotli |
| Icônes | `all.min.css` (~100 Ko) + `fa-solid-900.woff2` (155 Ko) depuis cdnjs | `icons.css` (6,5 Ko) + police sous-ensemblée (9,4 Ko), locales |
| Polices | `@import` vers fonts.googleapis.com puis fonts.gstatic.com | 4 fichiers woff2 locaux, `font-display: swap`, latin préchargé |
| Logo | `Logo.png`, 1978 Ko, affiché en 40 px | `logo-96.webp`, 2 Ko |
| Logo Google (connexion) | svgrepo.com | `static/images/google-color.svg` |

Origines tierces restantes sur les pages publiques : **aucune**, hors Google
Analytics quand `GA_MEASUREMENT_ID` est renseigné. Sur les pages connectées, il
reste TinyMCE (éditeur de lettres) et canvas-confetti — tous deux autorisés
explicitement dans la CSP.

### Régénérer les assets

```bash
make css      # recompile static/css/app.css  (obligatoire après ajout de classes)
make images   # régénère les variantes depuis assets/Logo.png
python scripts/build_icons.py <dossier @fortawesome/fontawesome-free>
```

`static/css/app.css` est un **artefact commité** : la production n'a pas besoin
de Node. La CI vérifie qu'il est à jour et échoue sinon — une classe ajoutée dans
un gabarit sans `make css` casserait la mise en page en production.

Le master du logo vit dans `assets/Logo.png`, hors de `static/`, pour que
`collectstatic` n'embarque pas 2 Mo inutiles.

### Pourquoi WebP et pas AVIF

Mesuré sur ce logo : à 96 px, l'AVIF pèse 5,5 Ko contre 2,0 Ko en WebP —
l'en-tête AVIF domine sur une image aussi petite. Le WebP est décodé par tous les
navigateurs visés (Safari ≥ 14), donc un `<picture>` avec repli PNG n'apporterait
qu'un chemin mort et un risque de régression de mise en page dans les conteneurs
flex. Les PNG restent produits pour les contextes qui ne négocient pas le format :
JSON-LD, image Open Graph, favicon, courriels (Outlook ne décode pas le WebP).

## 2. Compression texte

`django.middleware.gzip.GZipMiddleware` compresse le HTML et le JSON produits par
Django ; WhiteNoise sert les statiques précompressés en **brotli** puis gzip
(extra `whitenoise[brotli]`). Mesure sur la page d'accueil : 37,4 Ko → 8,0 Ko.

Gunicorn ne compresse rien lui-même — il n'a pas de module de compression. La
compression se fait donc au niveau applicatif (ci-dessus) ou au niveau du
reverse proxy, jamais « dans Gunicorn ».

À propos de BREACH : compresser une réponse contenant un jeton CSRF est
théoriquement exploitable. Django masque le jeton avec un aléa différent à chaque
réponse depuis la 4.1, ce qui neutralise l'attaque ; le projet est en Django 5.2.

## 3. Préconnexions

Seules subsistent celles vers `googletagmanager.com` et `google-analytics.com`,
posées dans `templates/partials/_analytics.html` et uniquement si GA est activé.

L'audit demandait une préconnexion vers l'API Google Gemini : **elle n'a pas
lieu d'être**. Gemini est appelé depuis le serveur Django, jamais depuis le
navigateur. Une préconnexion ouvrirait une connexion TLS que la page n'utiliserait
jamais, ce qui coûte des ressources au lieu d'en gagner. Idem pour France Travail
et Stripe (redirection serveur, pas d'iframe).

## 4. Accessibilité

- **heading-order** : plus aucun saut de niveau sur les pages publiques.
  Corrections : « Sommaire » des pages légales repassé en `<p>` (il précédait le
  `<h1>`), titres de cartes `h3` → `h2`, titres de pied de page `h4` → `h3`.
  `tests/test_performance_securite.py` vérifie la règle automatiquement sur les
  sept pages publiques — un futur changement de balise pour un effet visuel sera
  rattrapé par la CI.
- **color-contrast** : 51 occurrences de `text-slate-400` sur fond clair
  (2,56:1) remplacées par `text-slate-500` (4,76:1), ou `text-slate-600` sur
  `bg-slate-100` (6,92:1) pour la pagination désactivée. Sur le pied de page
  sombre, `text-slate-400` est conservé (6,96:1) et le libellé « Suivez-nous »,
  qui était en `slate-500` (3,75:1), passe en `slate-300` (12:1).
- Restent en dessous de 4,5:1 mais **exemptés** par WCAG 1.4.3 car purement
  décoratifs et redondants avec du texte adjacent : les icônes `text-amber-500`
  et `text-blue-500` sur fond blanc.
- `prefers-reduced-motion` : toutes les animations décoratives de l'accueil sont
  désactivées, ce qui n'était pas le cas avant.

## 5. En-têtes de sécurité

`JobPilot/middleware.py` pose `Content-Security-Policy` et `Permissions-Policy`
sur chaque réponse. HSTS, nosniff et le referrer restaient déjà à la charge de
`SecurityMiddleware`.

**Limite assumée** : `script-src` et `style-src` contiennent `'unsafe-inline'`.
Les gabarits utilisent des gestionnaires d'événements en ligne
(`onclick="togglePassword()"`) et des attributs `style=""` ; or un nonce ne
couvre pas les gestionnaires en ligne, seuls `'unsafe-inline'` les autorise. La
politique reste utile : elle verrouille les origines chargeables, interdit
l'inclusion en iframe (`frame-ancestors 'none'`), les plugins (`object-src
'none'`), la réécriture de `<base>` et l'envoi de formulaire hors du domaine.

Pour durcir vers une CSP à nonce, dans cet ordre :

1. déplacer les `onclick=` / `onsubmit=` des gabarits vers des `addEventListener`
   dans un fichier JS servi depuis `static/` ;
2. remplacer les `style="…"` restants par des classes ;
3. générer un nonce par requête et le poser sur chaque `<script>` interne ;
4. retirer `'unsafe-inline'` de `script-src`, puis de `style-src`.

`CSP_REPORT_ONLY=true` bascule l'en-tête en observation le temps de valider une
modification — à utiliser systématiquement après avoir introduit une origine
tierce dans un gabarit.

## 6. Ce qui n'a pas été fait, et pourquoi

- **Vérification visuelle dans un navigateur** : aucun navigateur n'est installé
  sur la machine de développement, le rendu n'a donc pas pu être contrôlé à
  l'œil après le passage du CDN Tailwind à la CSS compilée. Les garde-fous
  automatiques couvrent la présence des classes (y compris les valeurs
  arbitraires type `bg-[#125484]`, `aspect-[11/7]`), mais **une relecture
  visuelle des pages reste à faire avant mise en production**.
- **Témoignages clients** : le mécanisme est livré (modèle `Testimonial`,
  back-office, section d'accueil), pas le contenu. Un témoignage inventé est une
  pratique commerciale trompeuse (art. L121-2 du code de la consommation) et la
  personne citée doit avoir donné son accord — d'où le champ obligatoire
  `consent_reference`. La section reste invisible tant qu'aucun témoignage n'est
  publié.

## 7. Anomalies découvertes en chemin

- `fa-sparkles` est une icône Font Awesome **Pro** : elle n'a jamais pu
  s'afficher, même via le CDN. Remplacée par `fa-wand-magic-sparkles`.
- Le motif décoratif de la section d'appel à l'action était écrit en valeur
  arbitraire Tailwind contenant des guillemets doubles, ce qui refermait
  l'attribut `class` au milieu de la valeur : HTML invalide et motif jamais
  affiché. Déplacé dans `.cta-pattern`.
- `text-brand-600` / `hover:text-brand-700` (pages de connexion et d'inscription)
  référençaient une palette `brand` qui n'existait pas : ces liens héritaient de
  la couleur du texte. La palette est désormais définie dans `tailwind.config.js`.
- Les classes `prose` / `not-prose` des pages légales supposent le plugin
  `@tailwindcss/typography`, absent du projet. Sans effet aujourd'hui comme
  hier ; à installer si l'on veut la mise en forme associée.
- **Aucune résiliation d'abonnement en libre-service** n'existe côté
  application : `subscriptions.views.cancel_view` n'est que l'URL de retour
  d'un paiement Stripe abandonné. La page Tarifs indique donc une résiliation par
  courriel. La législation française impose depuis 2023 une résiliation en ligne
  aussi simple que la souscription : ce point est à traiter.
- La page d'accueil affiche « Rejoignez des milliers de candidats » et des
  compteurs (« +150 CVs analysés ») qui ne proviennent d'aucune donnée réelle.
  Même risque juridique que les faux témoignages : à brancher sur de vraies
  statistiques ou à retirer.
