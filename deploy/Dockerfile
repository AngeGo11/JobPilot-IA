# Image de l'application JobPilot-AI.
# Construction en deux étapes : les outils de compilation restent dans l'étape
# `builder` et n'atterrissent pas dans l'image finale.

# ---------- Étape 1 : dépendances ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances de compilation de psycopg2 et des bibliothèques PDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements/ requirements/
RUN pip wheel --wheel-dir /wheels -r requirements/prod.txt


# ---------- Étape 2 : image finale ----------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=JobPilot.settings

# libpq5 seul suffit à l'exécution ; le reste de la chaîne de compilation non.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non privilégié : un processus applicatif n'a aucune raison
# d'être root dans son conteneur.
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements/ requirements/
RUN pip install --no-index --find-links=/wheels -r requirements/prod.txt \
    && rm -rf /wheels

COPY --chown=app:app . .

# collectstatic à la construction plutôt qu'au démarrage : l'image est
# immuable et le conteneur démarre sans écrire sur le disque.
# Les variables factices satisfont les contrôles de settings sans jamais
# atterrir dans l'image finale (elles ne valent que pour cette commande).
RUN DJANGO_SECRET_KEY="build-only-placeholder-key-not-used-at-runtime-000" \
    ENVIRONMENT=build \
    DEBUG=false \
    python manage.py collectstatic --noinput --clear

USER app

EXPOSE 8000

# Vérification de vie : le conteneur est déclaré malade si Django ne répond plus.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/users/login/', timeout=4).status == 200 else 1)"

# --workers : la valeur par défaut de gunicorn est 1, ce qui rend le site
#   mono-utilisateur. 2 × cœurs + 1 est la recommandation usuelle.
# --timeout 60 : une requête web légitime ne dure pas dix minutes. Le travail
#   long doit passer par une tâche de fond, pas par un timeout allongé.
CMD ["gunicorn", "JobPilot.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--threads", "2", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
