# make dev : installe, charge .env.local, lance la passerelle. Personne ne tape export.
PY := $(shell command -v python3.11 || command -v python3)
VENV := .venv
BIN := $(VENV)/bin

.PHONY: dev install test lint record audit demo prices catalog

dev: install .env.local
	@set -a; . ./.env.local; set +a; \
	if [ -f gateway/__main__.py ]; then $(BIN)/python -m gateway; \
	else echo "gateway/__main__.py absent (D1.1) : environnement pret, rien a lancer."; fi

install: $(BIN)/.installed

$(BIN)/.installed: requirements.txt gateway/requirements.txt
	@$(PY) -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ requis"'
	$(PY) -m venv $(VENV)
	PIP_DISABLE_PIP_VERSION_CHECK=1 $(BIN)/pip install -q -r requirements.txt
	@touch $@

.env.local:
	cp .env.example .env.local
	@echo ".env.local cree depuis .env.example : aucune cle a remplir pour la passerelle ou la demo."

test: install
	$(BIN)/python -m pytest -q

lint: install
	$(BIN)/ruff check .

# appelle les vraies API une fois et ecrit tests/cassettes/ (cles de .env.local, jamais ecrites)
record: install .env.local
	@set -a; . ./.env.local; set +a; $(BIN)/python -m pytest -q --record-mode=once

# Même configuration que make dev ; export temporaire supprimé après le rapport.
AUDIT_OUT ?= out/audit.html
audit: install
	@set -a; if [ -f .env.local ]; then . ./.env.local; fi; set +a; \
	$(BIN)/python -m scripts.audit --out "$(AUDIT_OUT)"

# Aucune clé et aucune modification de la base client ; ports locaux libres.
demo: install
	$(BIN)/python -m scripts.demo

# prix OpenRouter (API publique, sans clé) -> fixtures/pricing.json ; anciens modèles conservés
prices: install
	$(BIN)/python -m collector.pricing

# M1 : rafraîchit les prix puis contrôle le catalogue (origine, hébergement, couverture)
catalog: prices
	$(BIN)/python -m catalog
