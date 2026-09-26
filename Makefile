# make dev : installe, charge .env.local, lance la passerelle. Personne ne tape export.
PY := $(shell command -v python3.11 || command -v python3)
VENV := .venv
BIN := $(VENV)/bin

.PHONY: dev install test lint

dev: install .env.local
	@set -a; . ./.env.local; set +a; \
	if [ -f gateway/__main__.py ]; then $(BIN)/python -m gateway; \
	else echo "gateway/__main__.py absent (D1.1) : environnement pret, rien a lancer."; fi

install: $(BIN)/.installed

$(BIN)/.installed: requirements.txt
	@$(PY) -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ requis"'
	$(PY) -m venv $(VENV)
	PIP_DISABLE_PIP_VERSION_CHECK=1 $(BIN)/pip install -q -r requirements.txt
	@touch $@

.env.local:
	cp .env.example .env.local
	@echo ".env.local cree depuis .env.example : remplis tes cles."

test: install
	$(BIN)/python -m pytest -q

lint: install
	$(BIN)/ruff check .
