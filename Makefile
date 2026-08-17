# Raccourcis de développement. `make aide` pour la liste.
#
# Le port hôte de PostgreSQL est configurable : DB_PORT_HOST=5434 make services
.DEFAULT_GOAL := aide
SHELL := /bin/bash
PY := .venv/bin/python
DB_PORT_HOST ?= 5433
export DB_PORT_HOST

.PHONY: aide services stop migrations migrer seed serveur worker beat tests verifier css images

aide:  ## Affiche cette aide
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

services:  ## Démarre PostgreSQL et Redis en local
	docker compose up -d db redis
	@echo "PostgreSQL sur 127.0.0.1:$(DB_PORT_HOST), Redis sur 127.0.0.1:6379"

stop:  ## Arrête les services locaux
	docker compose down

migrations:  ## Génère les migrations manquantes
	@source scripts/dev-env.sh && $(PY) manage.py makemigrations

migrer:  ## Applique les migrations sur la base locale
	@source scripts/dev-env.sh && $(PY) manage.py migrate

seed:  ## Peuple la base locale avec un jeu de démonstration
	@source scripts/dev-env.sh && $(PY) manage.py seed_demo --reset

serveur:  ## Lance le serveur de développement (port 8000)
	@source scripts/dev-env.sh && $(PY) manage.py runserver 8000

worker:  ## Lance un worker Celery (traitements IA)
	@source scripts/dev-env.sh && .venv/bin/celery -A JobPilot worker --loglevel=info

beat:  ## Lance le planificateur Celery (alertes, purges)
	@source scripts/dev-env.sh && .venv/bin/celery -A JobPilot beat --loglevel=info

css:  ## Recompile la feuille Tailwind (obligatoire après ajout de classes)
	npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i static/css/app.src.css -o static/css/app.css --minify

images:  ## Régénère les variantes d'images depuis assets/Logo.png
	$(PY) scripts/build_images.py

tests:  ## Exécute la suite de tests
	$(PY) manage.py test

verifier:  ## Contrôles Django, y compris ceux de déploiement
	@source scripts/dev-env.sh && $(PY) manage.py check
	@ENVIRONMENT=production DJANGO_SETTINGS_MODULE=JobPilot.settings.base $(PY) manage.py check --deploy 2>&1 | tail -20
