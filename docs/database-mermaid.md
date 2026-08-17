# Schéma de la base de données JobPilot

Diagramme Mermaid pour visualiser les modèles Django et leurs relations.

## Diagramme ER (Entity Relationship)

```mermaid
erDiagram
    CustomUser ||--o| CandidateProfile : "1-1 profile"
    CustomUser ||--o| StripeSubscription : "1-1 stripe_subscription"
    CustomUser ||--o{ Resume : "1-N resumes"
    CustomUser ||--o{ JobMatch : "user"

    Resume ||--o{ JobMatch : "matches"
    Resume ||--o| JobAlert : "job_alerts (1 par CV)"

    JobOffer ||--o{ JobMatch : "job_offer"

    CustomUser {
        int id PK
        string username
        string email UK
        int ai_credits
        datetime subscription_end_date
        string subscription_plan
    }

    CandidateProfile {
        int id PK
        int user_id FK "UK"
        string phone
        string location
        string target_rome_code
        bool is_available
    }

    Resume {
        int id PK
        int user_id FK
        string title
        string file
        datetime uploaded_at
        bool is_primary
        text extracted_text
        string detected_job_title
        json detected_skills
        json parsed_skills
        json parsed_data
    }

    StripeSubscription {
        int id PK
        int user_id FK "UK"
        string stripe_subscription_id UK
        datetime created_at
        datetime updated_at
    }

    JobOffer {
        int id PK
        string remote_id UK
        string title
        string company_name
        text description
        string url
        string location
        string contract_type
        datetime date_posted
        datetime created_at
        json raw_api_data
    }

    JobMatch {
        int id PK
        int resume_id FK "nullable"
        int user_id FK
        int job_offer_id FK
        int score
        string status
        datetime matched_at
        text cover_letter_content
    }

    JobAlert {
        int id PK
        int resume_id FK "UK"
        bool is_active
        datetime last_checked
        datetime created_at
    }
```

## Légende

| Symbole | Signification |
|---------|---------------|
| `\| \|--o\|` | Un à un (OneToOne) |
| `\| \|--o{` | Un à plusieurs (OneToMany / ForeignKey) |
| PK | Primary Key |
| UK | Unique |
| FK | Foreign Key |

## Résumé des modèles

| Modèle | App | Description |
|--------|-----|-------------|
| **CustomUser** | users | Utilisateur (email, crédits IA, abonnement) |
| **CandidateProfile** | users | Profil candidat (téléphone, lieu, code ROME, disponibilité) |
| **Resume** | resumes | CV (fichier, texte extrait, compétences détectées par IA) |
| **StripeSubscription** | subscriptions | Lien abonnement Stripe ↔ utilisateur |
| **JobOffer** | matching | Offre d'emploi (API France Travail) |
| **JobMatch** | matching | Match CV ↔ Offre (score, statut, lettre de motivation) |
| **JobAlert** | matching | Alerte email pour nouvelles offres (par CV) |

## Contraintes importantes

- **JobMatch** : `unique_together (resume, job_offer)` — un même CV ne peut matcher qu'une fois par offre.
- **JobAlert** : une seule alerte par CV (contrainte métier sur `resume`).
- **CandidateProfile** et **StripeSubscription** : un enregistrement maximum par utilisateur (OneToOne).
