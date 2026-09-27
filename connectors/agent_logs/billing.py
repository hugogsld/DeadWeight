"""Mode de facturation d'un agent de code : abonnement (Claude Code Pro/Max, ChatGPT Plus/Pro/Codex)
ou API à l'usage. Jamais deviné : on lit le fichier de configuration réel de l'outil, ou on
applique l'override explicite ``--billing``. Aucune valeur de jeton ou de clé n'est lue ni exposée :
seulement des noms de champs et des booléens.

Repères relevés sur une installation réelle (26/09/2026) :
- Claude Code : ``~/.claude.json``, objet ``oauthAccount`` présent avec ``billingType`` (ex.
  ``"stripe_subscription"``) quand la connexion est un abonnement Claude Pro/Max/Team ; sinon la
  variable d'environnement ``ANTHROPIC_API_KEY`` indique une facturation à l'usage.
- Codex : ``~/.codex/auth.json``, champ ``auth_mode`` (``"chatgpt"`` = abonnement ChatGPT ; une
  clé API ``OPENAI_API_KEY`` présente dans ce même fichier, ou ``auth_mode`` absent/différent,
  indique une facturation à l'usage).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ABONNEMENT, API, INCONNU = "abonnement", "api", "inconnu"

# valeurs de oauthAccount.billingType observées côté Claude Code pour un abonnement (Pro/Max/Team)
CLAUDE_CODE_SUBSCRIPTION_BILLING_TYPES = {"stripe_subscription", "subscription"}
# valeurs de auth_mode observées côté Codex pour un abonnement (ChatGPT Plus/Pro/Business)
CODEX_SUBSCRIPTION_AUTH_MODES = {"chatgpt"}
CODEX_API_AUTH_MODES = {"apikey", "api_key"}


def detect_claude_code(config_path: Path | None = None, env: dict | None = None) -> dict:
    """{mode, source} pour Claude Code : ``~/.claude.json`` d'abord, ``ANTHROPIC_API_KEY`` sinon."""
    env = env if env is not None else os.environ
    path = config_path or Path.home() / ".claude.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    oauth = data.get("oauthAccount")
    billing_type = oauth.get("billingType") if isinstance(oauth, dict) else None
    if isinstance(oauth, dict) and billing_type in CLAUDE_CODE_SUBSCRIPTION_BILLING_TYPES:
        return {"mode": ABONNEMENT, "source": f"{path}:oauthAccount.billingType"}
    if env.get("ANTHROPIC_API_KEY"):
        return {"mode": API, "source": "env:ANTHROPIC_API_KEY"}
    if isinstance(oauth, dict):
        # compte OAuth present mais type de facturation non reconnu : on ne devine pas
        return {"mode": INCONNU, "source": f"{path}:oauthAccount.billingType (valeur non reconnue)"}
    return {"mode": INCONNU, "source": None}


def detect_codex(auth_path: Path | None = None) -> dict:
    """{mode, source} pour Codex : ``~/.codex/auth.json``, champ ``auth_mode``."""
    path = auth_path or Path.home() / ".codex" / "auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mode": INCONNU, "source": None}
    auth_mode = data.get("auth_mode")
    if auth_mode in CODEX_SUBSCRIPTION_AUTH_MODES:
        return {"mode": ABONNEMENT, "source": f"{path}:auth_mode"}
    if auth_mode in CODEX_API_AUTH_MODES:
        return {"mode": API, "source": f"{path}:auth_mode"}
    if data.get("OPENAI_API_KEY"):
        return {"mode": API, "source": f"{path}:OPENAI_API_KEY"}
    return {"mode": INCONNU, "source": None}


DETECTORS = {"claude-code": detect_claude_code, "codex": detect_codex}


def resolve(tool: str, override: str | None = None) -> dict:
    """{mode, source} pour un outil reconnu. ``override`` (``--billing``) est prioritaire sur la
    détection : il vient d'une décision explicite de l'utilisateur, jamais d'une supposition."""
    if override in (ABONNEMENT, API):
        return {"mode": override, "source": "--billing (forcé)"}
    detector = DETECTORS.get(tool)
    return detector() if detector else {"mode": INCONNU, "source": None}
