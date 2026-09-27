# make dev : installe, charge .env.local, lance la passerelle. Personne ne tape export.
PY := $(shell command -v python3.11 || command -v python3)
VENV := .venv
BIN := $(VENV)/bin

.PHONY: dev install test lint record audit audit-complet demo prices e2e catalog tester

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

# Tout après la capture : bilan, optimisations testées sur l'historique, micro-PR.
# make optimiser REPO=chemin/du/depot [PR=oui] [BANC=oui]
OPTIM_OUT ?= out/optimiser
optimiser: install
	@set -a; if [ -f .env.local ]; then . ./.env.local; fi; set +a; \
	$(BIN)/python -m scripts.optimiser --out "$(OPTIM_OUT)" $(if $(REPO),--repo "$(REPO)") \
		$(if $(filter oui,$(PR)),--pr) $(if $(filter oui,$(BANC)),--banc)

# Aucune clé et aucune modification de la base client ; ports locaux libres.
demo: install
	$(BIN)/python -m scripts.demo

# prix OpenRouter (API publique, sans clé) -> fixtures/pricing.json ; anciens modèles conservés
prices: install
	$(BIN)/python -m collector.pricing

# M1/M2 : rafraîchit prix et capacités (OpenRouter, sans clé), puis contrôle le catalogue
catalog: prices
	$(BIN)/python -m catalog.capabilities
	$(BIN)/python -m catalog

# boucle complète de bout en bout (Q1) : passerelle réelle, trois fournisseurs simulés, rapport, preuve
e2e: install
	bash tests/e2e/run.sh

# une commande : détection (n8n:<id>, dossier n8n, gateway/.db, events.jsonl, journaux Claude Code/Codex),
# audit, micro-PR (REPO=… les ouvre avec gh), puis Slack si SLACK_WEBHOOK_URL (sinon slack.md seulement)
AUDIT_COMPLET_OUT ?= out/audit-complet
audit-complet: install
	@test -n "$(SOURCE)" || { echo "Usage : make audit-complet SOURCE=<n8n:id|dossier|gateway|events.jsonl|journaux> [REPO=…] [DEMO=1]"; exit 2; }
	@set -a; if [ -f .env.local ]; then . ./.env.local; fi; set +a; \
	$(BIN)/python -m scripts.audit_complet "$(SOURCE)" --out "$(AUDIT_COMPLET_OUT)" \
		$(if $(REPO),--repo "$(REPO)") $(if $(DEMO),--demo)

# scénario testeur guidé (O/n) : WF=<id n8n>, SOURCE par défaut n8n:<id> si N8N_URL, OUI=1 accepte tout
TESTER_OUT ?= out/tester
tester: install
	@test -n "$(WF)" || { echo "Usage : make tester WF=<id> [SOURCE=…] [REPO=…] [OUI=1]"; exit 2; }
	@set -a; if [ -f .env.local ]; then . ./.env.local; fi; set +a; \
	$(BIN)/python -m scripts.tester "$(WF)" --out "$(TESTER_OUT)" \
		$(if $(SOURCE),--source "$(SOURCE)") $(if $(REPO),--repo "$(REPO)") $(if $(OUI),--oui)
